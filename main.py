from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Any, Optional, Dict
from format_logic import format_sheet_data
import google.oauth2.credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json
import uuid
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Google Sheets Formatter",
    description="API for formatting Google Sheets data using Gemini AI",
    version="1.0.0"
)

# In-memory storage for formatted results (in production, use a proper database)
formatted_results: Dict[str, Dict] = {}
RESULT_EXPIRY = timedelta(hours=24)

# Initialize Google API credentials
SHEETS_CREDENTIALS = json.loads(os.getenv("GOOGLE_SHEETS_CREDENTIALS", "{}"))
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
DEFAULT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

class SchoolMetadata(BaseModel):
    school_type: str = Field(..., description="Type of school (primary, secondary, or k-12)")
    admin_lastname: Optional[str] = Field(None, description="Admin's last name")
    admin_firstname: Optional[str] = Field(None, description="Admin's first name")
    admin_title: Optional[str] = Field(None, description="Admin's title")
    admin_email: Optional[str] = Field(None, description="Admin's email address")
    folder_id: Optional[str] = Field(None, description="Google Drive folder ID for the school")

class FormatRequest(BaseModel):
    file_id: str = Field(..., description="Google Sheet file ID")
    metadata: SchoolMetadata = Field(..., description="School metadata from n8n")

class FormatResponse(BaseModel):
    request_id: str
    status: str
    message: str

class FormattedData(BaseModel):
    headers: List[str]
    rows: List[List[str]]

def get_google_service(api_name: str, version: str, scopes: List[str]):
    """Create a Google API service with the stored credentials."""
    try:
        credentials = service_account.Credentials.from_service_account_info(
            SHEETS_CREDENTIALS,
            scopes=scopes
        )
        return build(api_name, version, credentials=credentials)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error initializing Google {api_name} service: {str(e)}"
        )

def get_sheet_data(file_id: str) -> List[List[Any]]:
    """Fetch data from Google Sheet using service account credentials."""
    try:
        # Build the Sheets API service
        service = get_google_service(
            'sheets', 
            'v4', 
            ['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        
        # Get the sheet data
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=file_id,
            range='A1:Z'  # Adjust range as needed
        ).execute()
        
        return result.get('values', [])
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching sheet data: {str(e)}"
        )

def verify_file_access(file_id: str, folder_id: Optional[str] = None) -> bool:
    """Verify that the service account has access to the file."""
    try:
        # Build the Drive API service
        service = get_google_service(
            'drive',
            'v3',
            ['https://www.googleapis.com/auth/drive.readonly']
        )
        
        # Get file metadata
        file = service.files().get(
            fileId=file_id,
            fields='parents'
        ).execute()
        
        # If folder_id is provided, verify the file is in that folder
        if folder_id:
            return folder_id in file.get('parents', [])
        
        return True
        
    except Exception:
        return False

def cleanup_expired_results():
    """Remove expired results from storage."""
    current_time = datetime.now()
    expired_keys = [
        key for key, value in formatted_results.items()
        if current_time - value['timestamp'] > RESULT_EXPIRY
    ]
    for key in expired_keys:
        del formatted_results[key]

@app.post("/format-sheet", response_model=FormatResponse)
async def format_sheet(request: FormatRequest, background_tasks: BackgroundTasks):
    """
    Start the sheet formatting process.
    
    Args:
        request: FormatRequest containing file ID and school metadata
        background_tasks: FastAPI background tasks
        
    Returns:
        FormatResponse with request ID for tracking
    """
    try:
        # Verify file access
        folder_id = request.metadata.folder_id or DEFAULT_FOLDER_ID
        if not verify_file_access(request.file_id, folder_id):
            raise HTTPException(
                status_code=403,
                detail="Access denied to the specified file"
            )
        
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        
        # Store initial status
        formatted_results[request_id] = {
            'status': 'processing',
            'message': 'Starting sheet formatting',
            'timestamp': datetime.now(),
            'data': None
        }
        
        # Define background task
        async def process_sheet():
            try:
                # Fetch sheet data
                sheet_data = get_sheet_data(request.file_id)
                
                # Format the data
                formatted_data = format_sheet_data(sheet_data, request.metadata.dict())
                
                # Update result
                formatted_results[request_id].update({
                    'status': 'completed',
                    'message': 'Sheet formatting completed successfully',
                    'data': formatted_data
                })
                
            except Exception as e:
                formatted_results[request_id].update({
                    'status': 'error',
                    'message': f'Error processing sheet: {str(e)}',
                    'data': None
                })
        
        # Add task to background
        background_tasks.add_task(process_sheet)
        
        # Add cleanup task
        background_tasks.add_task(cleanup_expired_results)
        
        return FormatResponse(
            request_id=request_id,
            status='processing',
            message='Sheet formatting started'
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error starting sheet formatting: {str(e)}"
        )

@app.get("/format-status/{request_id}", response_model=Dict[str, Any])
async def get_format_status(request_id: str):
    """
    Get the status of a formatting request.
    
    Args:
        request_id: The unique request ID
        
    Returns:
        Current status and formatted data if available
    """
    if request_id not in formatted_results:
        raise HTTPException(
            status_code=404,
            detail="Request ID not found"
        )
    
    result = formatted_results[request_id]
    
    # If processing is complete, return the formatted data
    if result['status'] == 'completed':
        return {
            'status': result['status'],
            'message': result['message'],
            'data': result['data']
        }
    
    # Otherwise, just return the status
    return {
        'status': result['status'],
        'message': result['message']
    }

@app.get("/test-permissions")
async def test_permissions():
    """Test endpoint to verify Google API permissions."""
    results = {
        "sheets_api": False,
        "drive_api": False,
        "gemini_api": False,
        "details": {}
    }
    
    try:
        # Test Sheets API
        try:
            sheets_service = get_google_service(
                'sheets',
                'v4',
                ['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            # Try to list spreadsheets (this will fail if no access)
            sheets_service.spreadsheets().list().execute()
            results["sheets_api"] = True
            results["details"]["sheets"] = "Successfully connected to Sheets API"
        except Exception as e:
            results["details"]["sheets"] = f"Sheets API Error: {str(e)}"
        
        # Test Drive API
        try:
            drive_service = get_google_service(
                'drive',
                'v3',
                ['https://www.googleapis.com/auth/drive.readonly']
            )
            # Try to list files (this will fail if no access)
            drive_service.files().list(pageSize=1).execute()
            results["drive_api"] = True
            results["details"]["drive"] = "Successfully connected to Drive API"
        except Exception as e:
            results["details"]["drive"] = f"Drive API Error: {str(e)}"
        
        # Test Gemini API
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content("Test")
            results["gemini_api"] = True
            results["details"]["gemini"] = "Successfully connected to Gemini API"
        except Exception as e:
            results["details"]["gemini"] = f"Gemini API Error: {str(e)}"
        
        # Get service account info
        try:
            service_account_email = SHEETS_CREDENTIALS.get("client_email", "Not found")
            results["details"]["service_account"] = service_account_email
        except Exception as e:
            results["details"]["service_account"] = f"Error getting service account info: {str(e)}"
        
        return results
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error testing permissions: {str(e)}"
        )

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Google Sheets Formatter",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 