import json
import random
import datetime

def generate_object_id():
    # Generate 24 character hex string
    return ''.join(random.choices('0123456789abcdef', k=24))

def generate_sample(index):
    # Some basic randomization
    now = datetime.datetime.utcnow()
    start_time = now + datetime.timedelta(hours=random.randint(1, 48))
    end_time = start_time + datetime.timedelta(hours=random.randint(2, 24))
    
    disaster_types = ["Ocean Currents", "Storm Surge", "Heavy Rainfall", "Cyclone", "Tsunami"]
    severities = ["WARNING", "ALERT", "WATCH"]
    certainties = ["Likely", "Very Likely", "Observed"]
    
    disaster_type = random.choice(disaster_types)
    severity = random.choice(severities)
    certainty = random.choice(certainties)
    
    centroid_lat = 15.0 + random.random()
    centroid_long = 73.0 + random.random()
    
    doc = {
        "_id": {"$oid": generate_object_id()},
        "StateList": [{"stateId": 1297}],
        "DistrictList": [{"districtId": 15852}],
        "identifier": {"$numberLong": str(1738550000000000 + index)},
        "alert_id_sdma_autoinc": {"$numberLong": str(49800 + index)},
        "effective_start_time": {"$date": start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
        "effective_end_time": {"$date": end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
        "entry_time": {"$date": now.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
        "warning_message": f"Sample {severity} for {disaster_type}. Coastal regions may be affected.",
        "disaster_type": disaster_type,
        "certainty": certainty,
        "severity": severity,
        "area_covered": f"{random.uniform(1000, 5000):.3f}",
        "area_json": {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [centroid_long - 0.1, centroid_lat - 0.1],
                        [centroid_long + 0.1, centroid_lat - 0.1],
                        [centroid_long + 0.1, centroid_lat + 0.1],
                        [centroid_long - 0.1, centroid_lat + 0.1],
                        [centroid_long - 0.1, centroid_lat - 0.1]
                    ]
                ]
            ]
        },
        "alert_source": "INCOIS",
        "sender_org_id": "33",
        "second_message": "",
        "reference_id": str(15000 + index),
        "actual_lang": "",
        "alert_status_id": "2",
        "updated": "false",
        "disseminated": "false",
        "centroid": f"{centroid_long},{centroid_lat}",
        "xml_file_path": f"http://192.168.137.91/xmlFiles/sample_{index}.xml",
        "area_description": "Sample Zone of GOA",
        "info_id": str(21400 + index),
        "centroidPoint": {
            "type": "Point",
            "coordinates": [centroid_long, centroid_lat]
        },
        "max_lat": f"{centroid_lat + 0.1:.6f}",
        "min_lat": f"{centroid_lat - 0.1:.6f}",
        "min_long": f"{centroid_long - 0.1:.6f}",
        "max_long": f"{centroid_long + 0.1:.6f}"
    }
    
    return doc

samples = [generate_sample(i) for i in range(100)]

with open("sample_alerts.json", "w") as f:
    # write as a JSON array for standard mongoimport --jsonArray
    json.dump(samples, f, indent=2)

print("Generated sample_alerts.json with 100 documents.")
