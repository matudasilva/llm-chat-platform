# LLM Chat Platform

Base platform for an API built with **FastAPI**, designed as the backend of a **Large Language Model (LLM)–based chat system**.

The project includes a **Dockerized stack** with **PostgreSQL** and **Redis**, intended for persistence, caching, and future orchestration or messaging capabilities.

---

## Project Objectives

- Design a **scalable and secure** chat platform based on LLMs  
- Support multiple LLM providers (cloud and on-premises)  
- Apply **Cloud Architecture** and **MLOps / LLMOps** best practices  
- Serve as a **technical portfolio project** for Cloud & AI Architecture roles  

---

## Project Structure

```
llm-chat-platform/
├── app/        # API application code
├── infra/      # Infrastructure as Code (future)
├── docs/       # Technical and architectural documentation
├── scripts/    # Utility and operational scripts
├── .env.example
├── docker-compose.yml
└── README.md
```

## Requirements

- Docker  
- Docker Compose  

---

## Running the stack (development)

### 1. Copy environment variables

```bash
cp .env.example .env
```

### 2. Start services

```bash
docker compose up --build
```

## Quick verification

### API health check

```bash
curl http://127.0.0.1:8001/health
```

## Project status

🚧 **Initial phase – foundation stage**

The project currently includes:
- Base API up and running
- Environment-based configuration
- Structured logging
- Docker Compose–based containerization
- Core services (PostgreSQL and Redis)


## Documentation

Detailed technical documentation is available in the `docs/` directory, including the project's **Low Level Design (LLD)**.
