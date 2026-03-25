import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_upload_audio():
    dummy_file = "dummy_test_audio.mp3"
    
    # Create a simple dummy file
    with open(dummy_file, "wb") as f:
        f.write(b"dummy audio content")
    
    try:
        with open(dummy_file, "rb") as f:
            response = client.post(
                "/api/v1/upload/audio",
                files={"file": ("dummy_test_audio.mp3", f, "audio/mpeg")}
            )
            
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert "file_path" in data
        assert "data/uploads" in data["file_path"]
        
    finally:
        # Cleanup
        if os.path.exists(dummy_file):
            os.remove(dummy_file)
