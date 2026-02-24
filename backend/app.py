import uvicorn

from main import app  # noqa: F401 – imported for re-export

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
