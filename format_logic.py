import os
import re
import google.generativeai as genai
from typing import List, Dict, Any, Tuple, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('models/gemini-2.0-flash')

def clean_text(text: str) -> str:
    """Clean text by removing special characters and normalizing."""
    # Remove special characters and normalize Māori characters
    text = text.replace('ā', 'a').replace('ē', 'e').replace('ī', 'i').replace('ō', 'o').replace('ū', 'u')
    # Remove apostrophes
    text = text.replace("'", "")
    return text.strip()

def extract_names(full_name: str) -> Tuple[str, str]:
    """Extract first and last name from a full name string."""
    # Use Gemini to intelligently split names
    prompt = f"""Given this name, split it into first name and last name. Return in JSON format:
    {{
        "first_name": "first name here",
        "last_name": "last name here"
    }}
    
    Name: {full_name}
    """
    
    try:
        response = model.generate_content(prompt)
        import json
        names = json.loads(response.text)
        return clean_text(names["last_name"]), clean_text(names["first_name"])
    except:
        # Fallback to basic splitting
        parts = full_name.split()
        if len(parts) >= 2:
            return clean_text(parts[-1]), clean_text(" ".join(parts[:-1]))
        return clean_text(full_name), ""

def determine_year_group(class_name: str, school_type: str) -> str:
    """Determine year group from class name or school type."""
    # Try to extract year from class name
    year_match = re.search(r'(?:year|yr)?\s*(\d+|[kK])', class_name, re.IGNORECASE)
    if year_match:
        year = year_match.group(1).upper()
        return year if year == 'K' else year
    
    # Default based on school type
    defaults = {
        "secondary": "9",
        "primary": "2",
        "k-12": "6"
    }
    return defaults.get(school_type.lower(), "")

def format_sheet_data(sheet_data: List[List[Any]], metadata: Optional[Dict] = None) -> Dict[str, List[List[str]]]:
    """
    Format sheet data into standardized structure with student and teacher information.
    
    Args:
        sheet_data: 2D list of rows from Google Sheets
        metadata: Optional metadata from n8n containing school type and admin info
        
    Returns:
        Dict containing headers and formatted rows
    """
    # Convert sheet data to string for Gemini analysis
    sheet_str = "\n".join(["\t".join(str(cell) for cell in row) for row in sheet_data])
    
    # Create detailed prompt for Gemini
    prompt = f"""Analyze this spreadsheet data and format it according to these rules:
    1. Identify student names, class names, and teacher information
    2. For each student:
       - Split names into last name (col A) and first name (col B)
       - Identify their class (col C)
       - Determine year group (col D) - use K for kindergarten, numbers 1-12 for other years
       - Extract teacher's last name (col E), first name (col F), and title (col G)
       - Leave columns H and I blank
       - Add teacher's email if available (col J)
    3. For duplicate students (same name in different classes):
       - Keep first occurrence
       - Add second class info in columns K-O
       - Only match if classes are within 1 year of each other
    4. Use metadata for missing teacher info:
       School Type: {metadata.get('school_type', '') if metadata else ''}
       Admin Name: {metadata.get('admin_name', '') if metadata else ''}
       Admin Email: {metadata.get('admin_email', '') if metadata else ''}
    
    Spreadsheet data:
    {sheet_str}
    
    Return the data in this exact JSON format:
    {{
        "headers": ["Last Name", "First Name", "Class", "Year", "Teacher Last", "Teacher First", 
                   "Teacher Title", "", "", "Teacher Email", "Second Class", "Second Teacher Last",
                   "Second Teacher First", "Second Teacher Title", "Second Teacher Email"],
        "rows": [
            ["last", "first", "class", "year", "tlast", "tfirst", "title", "", "", "email",
             "sclass", "stlast", "stfirst", "sttitle", "stemail"],
            ...
        ]
    }}
    """
    
    try:
        # Get response from Gemini
        response = model.generate_content(prompt)
        import json
        formatted_data = json.loads(response.text)
        
        # Post-process the data
        processed_rows = []
        seen_students = {}  # Track students for duplicate detection
        
        for row in formatted_data["rows"]:
            # Clean and normalize all values
            row = [clean_text(str(cell)) for cell in row]
            
            # Check for duplicate students
            student_key = f"{row[0]}_{row[1]}"  # last name + first name
            if student_key in seen_students:
                # Check if this is a valid duplicate (within 1 year)
                prev_row = seen_students[student_key]
                prev_year = int(prev_row[3]) if prev_row[3].isdigit() else 0
                curr_year = int(row[3]) if row[3].isdigit() else 0
                
                if abs(prev_year - curr_year) <= 1:
                    # Update previous row with second class info
                    prev_row[10:15] = row[2:7]  # Copy class and teacher info to second class columns
                    continue
            
            seen_students[student_key] = row
            processed_rows.append(row)
        
        return {
            "headers": formatted_data["headers"],
            "rows": processed_rows
        }
        
    except Exception as e:
        # Fallback to basic formatting
        return basic_format(sheet_data, metadata)

def basic_format(sheet_data: List[List[Any]], metadata: Optional[Dict] = None) -> Dict[str, List[List[str]]]:
    """
    Basic fallback formatting when Gemini fails.
    Implements a simpler version of the formatting logic.
    """
    headers = ["Last Name", "First Name", "Class", "Year", "Teacher Last", "Teacher First",
              "Teacher Title", "", "", "Teacher Email", "Second Class", "Second Teacher Last",
              "Second Teacher First", "Second Teacher Title", "Second Teacher Email"]
    
    formatted_rows = []
    current_class = ""
    current_teacher = {"last": "", "first": "", "title": "", "email": ""}
    school_type = metadata.get("school_type", "") if metadata else ""
    
    for row in sheet_data:
        if not row or not any(cell for cell in row if str(cell).strip()):
            continue
            
        # Clean row data
        row = [str(cell).strip() if cell else "" for cell in row]
        
        # Try to identify class and teacher info
        for cell in row:
            if re.search(r'(?:year|yr|class|room)', cell, re.IGNORECASE):
                current_class = cell
            elif re.search(r'(?:mr|mrs|miss|ms|dr)', cell, re.IGNORECASE):
                current_teacher["title"] = cell
            elif "@" in cell:
                current_teacher["email"] = cell
        
        # Process student names
        if len(row) >= 2 and not any(re.search(r'(?:mr|mrs|miss|ms|dr)', cell, re.IGNORECASE) for cell in row):
            last_name, first_name = extract_names(row[0])
            year = determine_year_group(current_class, school_type)
            
            formatted_row = [
                last_name,
                first_name,
                current_class,
                year,
                current_teacher["last"],
                current_teacher["first"],
                current_teacher["title"],
                "",  # Column H
                "",  # Column I
                current_teacher["email"],
                "",  # Second class columns
                "",
                "",
                "",
                ""
            ]
            formatted_rows.append(formatted_row)
    
    return {
        "headers": headers,
        "rows": formatted_rows
    } 