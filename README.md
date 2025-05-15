# Google Sheets Formatter Agent

A FastAPI-based web service that intelligently formats Google Sheets data into a consistent structure using Google's Gemini AI.

## Features

- Accepts Google Sheets JSON data via POST request
- Uses Gemini 2.0 Flash to intelligently interpret and restructure sheet data
- Handles varying input formats and inconsistent data
- Standardizes output to a consistent JSON structure
- Detects headers automatically
- Fills missing values appropriately
- Ignores metadata and junk rows

## Setup

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file and add your Google API key:
   ```
   GOOGLE_API_KEY=your_api_key_here
   ```
4. Run the server:
   ```bash
   uvicorn main:app --reload
   ```

## API Usage

### POST /format-sheet

Accepts JSON data from Google Sheets and returns formatted output.

#### Input Example:
```json
{
  "sheetData": [
    ["Meta", "Junk"],
    [],
    ["Name", "Age", "Dept"],
    ["Alice", 30, "HR"],
    ["Bob", 25]
  ]
}
```

#### Output Example:
```json
{
  "headers": ["Name", "Age", "Dept"],
  "rows": [
    ["Alice", "30", "HR"],
    ["Bob", "25", "N/A"]
  ]
}
```

## Requirements

- Python 3.8+
- FastAPI
- Google Generative AI SDK
- Valid Google API key with Gemini access 