# Threadline
An agentic AI platform that turns scattered university notices into adaptive action plans.

# how to run the webapp (on vscode)
Download zip file of project and open it on vscode

cd backend

python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt

python3 -c "import pydantic, fastapi; print('ok')"

python3 -m pytest


### New terminal:

cd backend

source .venv/bin/activate      # if you're not already in it

uvicorn app.main:app --reload


### New terminal:

cd frontend

python3 -m http.server 5500

### note: frontend is on 5500 and backend is on 8000
