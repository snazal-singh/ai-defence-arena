# icarKno - Document Intelligence Platform

> An AI-powered document analysis platform that enables intelligent querying, summarization, and knowledge extraction from various document formats.

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-2.3+-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-proprietary-red.svg)](LICENSE)

## ✨ Features

### 📄 Document Processing

- **Multi-format Support**: PDF, DOCX, DOC, TXT, PPTX, CSV, XLSX
- **Intelligent Chunking**: Hierarchical text segmentation for optimal retrieval
- **Vector Embeddings**: Advanced semantic search using OpenAI embeddings

### 🔍 Smart Search & Retrieval

- **Hybrid Search**: Combines keyword and vector search for best results
- **Contextual Answers**: AI-powered responses with source citations
- **Creative Reasoning**: Advanced multi-step analysis for complex queries

### 🧠 AI Capabilities

- **Document Summarization**: Extractive and abstractive summaries
- **Question Answering**: Natural language queries with source attribution
- **Knowledge Graphs**: Visual representation of document relationships
- **Multi-language**: Support for 23+ languages including Hindi, Tamil, Bengali

### 📊 Data Integration

- **Structured Data**: Query CSV/Excel files using natural language
- **SQL Generation**: Automatic conversion of questions to database queries
- **Hybrid Analysis**: Combine document insights with data analytics

### 🌐 Integration & Access

- **REST API**: Complete programmatic access
- **WhatsApp Bot**: Chat with your documents via WhatsApp
- **Web Interface**: User-friendly document upload and query interface
- **Authentication**: JWT-based secure access with subscription tiers

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Elasticsearch cluster (cloud or self-hosted)
- OpenAI API access
- MySQL database
- MongoDB instance

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/your-org/icarkno.git
   cd icarkno
   ```

2. **Create virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Environment setup**

   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Configure environment variables**

   ```env
   # Elasticsearch
   ES_CLOUD_ID=your-elasticsearch-cloud-id
   ES_API_KEY=your-elasticsearch-api-key

   # Database
   MONGO_URL=mongodb://localhost:27017/icarkno
   MYSQL_HOST=localhost
   MYSQL_USERNAME=your-username
   MYSQL_PASSWORD=your-password

   # Security
   JWT_SECRET_KEY=your-jwt-secret
   SECRET_KEY=your-flask-secret
   ```

6. **Run the application**
   ```bash
   python run.py
   ```

The API will be available at `http://localhost:5000`

## 📖 Usage

### Basic Document Processing

```bash
# Upload documents
curl -X POST http://localhost:5000/upload \
  -F "files=@document.pdf" \
  -F "token=your-jwt-token" \
  -F "sessionId=session123"

# Query documents
curl -X POST http://localhost:5000/ask \
  -H "Content-Type: application/json" \
  -d '{
    "token": "your-jwt-token",
    "sessionId": "session123",
    "message": "What are the key findings?",
    "context": true
  }'
```

### Free Trial Mode

```bash
# Upload for trial users
curl -X POST http://localhost:5000/freeTrial \
  -F "files=@document.pdf" \
  -F "fingerprint=unique-browser-fingerprint"

# Query in trial mode
curl -X POST http://localhost:5000/trialAsk \
  -H "Content-Type: application/json" \
  -d '{
    "fingerprint": "unique-browser-fingerprint",
    "message": "Summarize this document"
  }'
```

### Advanced Features

- **Creative Mode**: Add `"mode": "creative"` for multi-step reasoning
- **Multi-language**: Set `"outputLanguage": 1` for Hindi responses
- **Data Queries**: Upload CSV/Excel and query with natural language

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Client Apps   │    │   Flask API      │    │   AI Services   │
│                 │────│                  │────│                 │
│ • Web Interface │    │ • Authentication │    │ • OpenAI GPT    │
│ • WhatsApp Bot  │    │ • Rate Limiting  │    │ • Embeddings    │
│ • Mobile App    │    │ • File Processing│    │ • Summarization │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                       ┌────────┴────────┐
                       │   Data Layer    │
                       │                 │
                       │ • Elasticsearch │
                       │ • MongoDB       │
                       │ • MySQL         │
                       │ • Neo4j         │
                       └─────────────────┘
```

## 📁 Project Structure

```
icarkno/
├── app/                    # Flask application
│   ├── __init__.py        # App factory
│   ├── api/               # API blueprints
│   ├── services/          # Business logic
│   └── config.py          # Configuration
├── controllers/           # Legacy controllers
├── elastic/              # Elasticsearch integration
├── utils/                # Utilities
├── webhook/              # WhatsApp integration
├── requirements.txt      # Dependencies
├── run.py               # Application entry point
└── README.md            # This file
```

## 🔧 Configuration

### Environment Variables

| Variable         | Description               | Required |
| ---------------- | ------------------------- | -------- |
| `ES_CLOUD_ID`    | Elasticsearch Cloud ID    | Yes      |
| `ES_API_KEY`     | Elasticsearch API Key     | Yes      |
| `OPENAI_API_KEY` | OpenAI API Key            | Yes      |
| `MONGO_URL`      | MongoDB connection string | Yes      |
| `MYSQL_HOST`     | MySQL host                | Yes      |
| `JWT_SECRET_KEY` | JWT signing key           | Yes      |

### Supported File Formats

- **Documents**: PDF, DOCX, DOC, TXT, PPTX
- **Data**: CSV, XLSX, XLS
- **Max file size**: 50MB per file
- **Supported languages**: 23+ languages

## 🔌 API Reference

See [API Documentation](api-documentation.md) for detailed endpoint information.

### Key Endpoints

- `POST /upload` - Upload documents
- `POST /ask` - Query documents
- `POST /freeTrial` - Trial mode upload
- `POST /trialAsk` - Trial mode queries
- `GET /healthcheck` - Health status

## 🚀 Deployment

### Docker (Recommended)

```bash
docker build -t icarkno .
docker run -p 5000:5000 --env-file .env icarkno
```

### Production Setup

```bash
# Using Gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 4 run:app

# With SSL
gunicorn --bind 0.0.0.0:443 --certfile cert.pem --keyfile key.pem run:app
```

## 📊 Performance

- **Processing Speed**: ~2-5 seconds per page
- **Concurrent Users**: Supports 100+ simultaneous users
- **Storage**: Elasticsearch scales horizontally
- **Languages**: 23+ supported with translation API
- **Rate Limits**: Configurable per user tier

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is proprietary software. See [LICENSE](LICENSE) for details.

## 🆘 Support

- **Documentation**: [API Docs](api-documentation.md)
- **Email**: support@carnotresearch.com

## 🙏 Acknowledgments

- [OpenAI](https://openai.com) for GPT and embedding models
- [Elasticsearch](https://elastic.co) for search and analytics
- [LangChain](https://langchain.com) for LLM orchestration
- [Flask](https://flask.palletsprojects.com) for the web framework

---

<p align="center">
  Made with ❤️ by <a href="https://carnotresearch.com">Carnot Research</a>
</p>

## AI Red Team Arena

The existing FastAPI backend now serves a separate live security dashboard at **`/arena`**.
Chatbot routes keep their existing behavior and emit privacy-preserving telemetry. The display
includes attack detection, evidence-based outcomes, SSE updates/replay, charts, a leaderboard,
and clearly separated simulation mode.

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 5000 --env-file .env
# Dashboard: http://localhost:5000/arena
```

See [REDTEAM_ARENA.md](REDTEAM_ARENA.md) for setup, nickname integration in the separate chatbot
frontend, configuration, API/schema contracts, response criteria, simulation, and tests.
