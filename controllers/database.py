"""
Database operations module for MongoDB interactions.

This module provides functions for:
- User authentication and management
- Trial status checking
- Database connection and operations
"""

# Standard library imports
import logging
from datetime import date, datetime, timedelta, timezone

# Third-party imports
from pymongo import MongoClient
from app.core.config import settings
import jwt
import hashlib
import hmac
from bson import ObjectId

# MongoDB configuration
mongo_url = settings.MONGO_URL
jwt_secret = "secret"
client = MongoClient(mongo_url)
db = client.test
collection = db.users


def check_trial_status(fingerprint):
    """
    Check if a user is eligible for a free trial.
    
    Args:
        fingerprint (str): User's fingerprint identifier
        
    Returns:
        bool: True if the user is eligible for a free trial, False otherwise
    """
    condition = {"fingerprint": str(fingerprint)}
    fingerprint_collection = db.fingerprint
    fingerprint_detail = fingerprint_collection.find_one(condition)
    
    if fingerprint_detail and fingerprint_detail.get('freeTrial') == 'true':
        return False

    # Add entry to fingerprint collection
    new_entry = {
        "fingerprint": str(fingerprint),
        "freeTrial": "true",
        "message": 0
    }
    fingerprint_collection.insert_one(new_entry)

    return True


def create_fingerprint_entry(fingerprint):
    """
    Create or reset a fingerprint entry in the database.
    
    Args:
        fingerprint (str): User's fingerprint identifier
    """
    fingerprint_collection = db.fingerprint
    condition = {"fingerprint": str(fingerprint)}

    # Check if the fingerprint already exists
    if fingerprint_collection.find_one(condition):
        # Reset message count to 0 if the entry exists
        fingerprint_collection.update_one(condition, {"$set": {"message": 0}})
        return

    # Create a new entry if it does not exist
    fingerprint_collection.insert_one({
        "fingerprint": str(fingerprint),
        "message": 0
    })


def is_trial_limit_over(fingerprint):
    """
    Check if a user has exceeded the free trial message limit.
    
    Args:
        fingerprint (str): User's fingerprint identifier
        
    Returns:
        bool: True if the user has exceeded the trial limit, False otherwise
    """
    trial_message_limit = 10
    condition = {"fingerprint": str(fingerprint)}
    fingerprint_collection = db.fingerprint
    fingerprint_detail = fingerprint_collection.find_one(condition)

    if fingerprint_detail and fingerprint_detail.get('message', 0) >= trial_message_limit:
        return True

    # Increment the 'message' field
    fingerprint_collection.update_one(
        condition,
        {"$inc": {"message": 1}}
    )

    return False


def is_user_limit_over(session_name):
    """
    Check if a user has exceeded their query limit.
    
    Args:
        session_name (str): User's session identifier
        
    Returns:
        bool: True if the user has exceeded their limit, False otherwise
    """
    condition = {"email": str(session_name)}
    user_details = collection.find_one(condition)
    
    paid = 0
    if user_details:
        if user_details.get('paid'):
            paid = int(user_details.get('paid'))
    else:
        # User not found (Illegal login)
        return True

    if paid == 0:
        queries = int(user_details.get('queries'))
        if queries < 10:
            # Increment the queries count
            result = collection.update_one(
                condition, 
                {"$inc": {"queries": 1}}
            )
            logging.info(f"Matched {result.matched_count} document(s) and modified {result.modified_count} document(s).")
        elif queries >= 10:
           return True

    return False


def upgrade_account(email, plan_limit_days):
    """
    Upgrade a user's account with a new payment plan.
    
    Args:
        email (str): User's email address
        plan_limit_days (int): Number of days for the plan
        
    Returns:
        int: Number of documents modified (1 if successful, 0 if not found)
    """
    # Calculate expiry date
    expiry_date = date.today() + timedelta(days=plan_limit_days)

    # Convert to YYYYMMDD format
    expiry_date_int = int(expiry_date.strftime("%Y%m%d"))
    logging.info(f"Expiry date (YYYYMMDD): {expiry_date_int}")

    # Find the document with the given email and update it
    result = collection.update_one(
        {'email': email},
        {'$set': {'paid': 1, 'expiry_date': expiry_date_int}}
    )

    return result.modified_count


def get_account_status(email):
    """
    Get a user's account status and remaining days.
    
    Args:
        email (str): User's email address
        
    Returns:
        int: Number of days remaining (-1 if not paid)
    """
    # Get user from database
    user = collection.find_one({'email': email})
    
    if user:
        payment_status = user.get('paid', 0)
        expiry_date_int = user.get('expiry_date', 0)  # Get expiry_date as int

        expiry_date_str = str(expiry_date_int)  # Convert int to string
        expiry_date = datetime.strptime(expiry_date_str, "%Y%m%d").date()
        remaining_days = (expiry_date - date.today()).days
        logging.info(f'Remaining days for user: {remaining_days}')

        status = 'paid' if payment_status != 0 else 'not paid'
        if status == 'paid':
            return remaining_days

    return -1

def sha512(password, salt):
    hash_obj = hmac.new(salt.encode(), password.encode(), hashlib.sha512)
    return hash_obj.hexdigest()

def salt_hash_password(user_password, secret):
    password_hash = sha512(user_password, secret)
    logging.info(f"Password hash = {password_hash}")
    return password_hash

def validate_user(email, password):
    """
    Authenticate a user by email and password.
    
    Args:
        email (str): User's email address
        password (str): User's password
    Returns:
        bool: True if authentication is successful, False otherwise
    """
    user = collection.find_one({'email': email})

    if not user:
        return False, {'message': 'User not found', 'code': 404}
    
    try:
        saved_password = user.get('password')
        hashed_password = salt_hash_password(password, jwt_secret)
        logging.info(f"comparing passwords: {saved_password}, {hashed_password}")
        if saved_password != hashed_password:
            return False, {'message': 'Invalid password', 'code': 401}
        token = jwt.encode(
            {"email": email},
            jwt_secret,
            algorithm="HS256"
        )
        validated_user = {'email': email, 'token': token, 'expiry_date': user.get('expiryDate')}
        return True, validated_user
    except Exception as e:
        logging.exception(f'Error during authentication: {e}')
        return False, {'message': 'Authentication error', 'code': 500}

def create_session(email, session_id, files):
    """
    Create a new session for a user in the sessions collection.
    
    Args:
        email (str): User's email
        session_id (str): Unique session identifier
        files (list): List of dicts with file info (expects `fileName` key)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        collection = db.sessions

        # Fetch the user document to count existing sessions
        user_doc = collection.find_one({"user_email": email})
        existing_sessions_count = len(user_doc.get("sessions", [])) if user_doc else 0

        # Extract file names
        file_names = [f.filename for f in files]

        # Create session data
        session_data = {
            "session_id": session_id,
            "file_names": file_names,
            "name": f"Knowledge container {existing_sessions_count + 1}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logging.info(f"Database update: {session_data}")

        # Insert or update user doc
        result = collection.update_one(
            {"user_email": email},
            {"$push": {"sessions": session_data}},
            upsert=True
        )

        if result.upserted_id:
            logging.info(f"New user created with ID: {result.upserted_id}")
        else:
            logging.info(f"User updated, modifiedCount={result.modified_count}")

        return True

    except Exception as e:
        logging.error(f"Error creating session for {email}: {e}")
        return False

def add_files_to_session(email, session_id, file_names):
    try:
        result = db.sessions.update_one(
            {"user_email": email, "sessions.session_id": session_id},
            {"$push": {"sessions.$.file_names": {"$each": file_names}}}
        )
        if result.matched_count == 0:
            logging.warning(f"No session found for email {email} with session_id {session_id}")
            return False
        logging.info(f"Added {len(file_names)} files to session {session_id}")
        return True
    except Exception as e:
        logging.error(f"Error adding files to session {session_id}: {e}")
        return False

def rename_session(session_id, new_name):
    """
    Rename a user's container.
    
    Args:
        session_id (str): User's session identifier
        new_name (str): New name for the container
        
    Returns:
        bool: True if renaming was successful, False otherwise
    """
    try:
        result = db.sessions.update_one(
            {"sessions.session_id": session_id},  # Find the document with this session_id
            {"$set": {"sessions.$.name": new_name}}  # Update the name of that session
        )

        if result.matched_count == 0:
            logging.warning(f"No session found with session_id: {session_id}")
            return False

        logging.info(f"Renamed session {session_id} to {new_name}")
        return True

    except Exception as e:
        logging.error(f"Error renaming session {session_id}: {e}")
        return False

def update_session_timestamp(email, session_id):
    """
    Update the timestamp of a given session inside the sessions array.

    Args:
        email (str): User's email
        session_id (str): Session identifier

    Returns:
        bool: True if update was successful, False otherwise
    """
    try:
        # Generate timestamp in YYYYMMDDTHHMMSS format
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

        result = db.sessions.update_one(
            {"user_email": email, "sessions.session_id": session_id},
            {"$set": {"sessions.$.timestamp": timestamp}}
        )

        if result.matched_count == 0:
            logging.warning(f"No session found for email {email} with session_id {session_id}")
            return False

        logging.info(f"Updated timestamp for session {session_id} to {timestamp}")
        return True

    except Exception as e:
        logging.error(f"Error updating timestamp for session {session_id}: {e}")
        return False

def delete_session_from_db(email, session_id):
    """
    Delete a session object from the sessions array for the given user email.

    Args:
        email (str): User's email
        session_id (str): Session identifier

    Returns:
        bool: True if deletion was successful, False otherwise
    """
    try:
        db.sessions.update_one(
            {"user_email": email},
            {"$pull": {"sessions": {"session_id": session_id}}}
        )
        return True
    except Exception as e:
        logging.error(f"Error deleting session {session_id} for user {email}: {e}")
        return False

def remove_file_from_session(session_id: str, filename: str) -> bool:
    """
    Remove a filename entry from the file_names array of a session.

    Args:
        session_id (str): Session identifier
        filename (str): Filename to remove

    Returns:
        bool: True if the update was applied, False if no matching session was found
    """
    try:
        result = db.sessions.update_one(
            {"sessions.session_id": session_id},
            {"$pull": {"sessions.$.file_names": filename}},
        )
        if result.matched_count == 0:
            logging.warning(f"No session found with session_id: {session_id}")
            return False
        logging.info(f"Removed '{filename}' from session {session_id}")
        return True
    except Exception as e:
        logging.error(f"Error removing file '{filename}' from session {session_id}: {e}")
        return False


def get_user_sessions(email):
    """
    Retrieve all sessions for a given user email.

    Args:
        email (str): User's email
    Returns:
        list: List of session objects
    """
    try:
        user_sessions = db.sessions.find_one({"user_email": email})
        if user_sessions and 'sessions' in user_sessions:
            if "_id" in user_sessions and isinstance(user_sessions["_id"], ObjectId):
                user_sessions["_id"] = str(user_sessions["_id"])
            user_sessions["sessions"].sort(key=lambda s: s.get("timestamp", ""), reverse=True)
            user_sessions["sessions"] = user_sessions["sessions"][:5]
            return user_sessions
        return []
    except Exception as e:
        logging.error(f"Error retrieving sessions for user {email}: {e}")
        return []
