from fastapi import FastAPI, UploadFile, File, Response, HTTPException
from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from fpdf import FPDF
import os
import logging

app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set Google Cloud credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'apikey/voicetonotes-7a838553c475.json'


def upload_blob(bucket_name: str, source_file_path: str, destination_blob_name: str) -> str:
    """Uploads a file to a Google Cloud Storage bucket."""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)

        blob.upload_from_filename(source_file_path)
        logger.info(f"Uploaded file to gs://{bucket_name}/{destination_blob_name}")

        return f"gs://{bucket_name}/{destination_blob_name}"
    except Exception as e:
        logger.error(f"Error uploading blob: {e}")
        raise


def delete_blob(bucket_name: str, blob_name: str):
    try:
        client = storage.Client()
        bucket = client.get_bucket(bucket_name)
        bucket.delete_blob(blob_name)
    except Exception as e:
        logger.error(f"Couldn't delete file: {e}")
        raise


def get_notes(source_file_path: str) -> str:
    try:
        project_id = "voicetonotes"
        vertexai.init(project=project_id, location="us-east1")
        model = GenerativeModel(model_name="gemini-1.5-flash-001")

        prompt = """
        Please provide notes for the audio with titles for various sections.
        Start the title in "#" and the subheadings in "*", and the pointers with "-", and give accurate symbols if any used.
        """

        destination_blob_name = f"{os.path.splitext(source_file_path)[0]}_uploaded.mp3"

        uri_location = upload_blob("voicetonotes", source_file_path, destination_blob_name)
        audio_file = Part.from_uri(uri_location, mime_type="audio/mpeg")
        contents = [audio_file, prompt]

        response = model.generate_content(contents)
        note_file_path = f"{os.path.splitext(source_file_path)[0]}.txt"
        with open(note_file_path, "w", encoding="utf-8") as f:
            f.write(response.text)

        logger.info("Notes created successfully")
        delete_blob("voicetonotes", destination_blob_name)
        return note_file_path
    except Exception as e:
        logger.error(f"Error generating notes: {e}")
        raise


def pdf_maker(text_file_path: str) -> str:
    try:
        pdf = FPDF("P", "mm", "letter")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.add_font("JetBrainsMono-Regular", "", "fonts/JetBrainsMono-Regular.ttf")
        pdf.add_font("JetBrainsMono-ExtraBold", "", "fonts/JetBrainsMono-ExtraBold.ttf")
        pdf.set_font("JetBrainsMono-Regular", "", 16)
        pdf.set_margin(15)

        with open(text_file_path, "r", encoding="utf-8") as file:
            lines = file.read().splitlines()
            for line in lines:
                if "#" in line:
                    pdf.set_font("JetBrainsMono-ExtraBold", "U", 20)
                    pdf.write(10, line + "\n")
                elif "*" in line:
                    pdf.set_font("JetBrainsMono-ExtraBold", "", 16)
                    pdf.write(10, line + "\n")
                else:
                    pdf.set_font("JetBrainsMono-Regular", "", 14)
                    pdf.write(8, line + "\n")

        pdf_file_path = f"{os.path.splitext(text_file_path)[0]}.pdf"
        pdf.output(pdf_file_path)
        logger.info("PDF created successfully")
        return pdf_file_path
    except Exception as e:
        logger.error(f"Error creating PDF: {e}")
        raise


@app.post("/process_audio")
async def process_audio(audio_file: UploadFile = File(...)):
    """Processes uploaded audio file and returns generated PDF."""
    try:
        # Save the uploaded file
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, audio_file.filename)
        with open(file_path, "wb") as f:
            f.write(await audio_file.read())
        logger.info(f"Audio file saved at {file_path}")

        # Generate notes and create PDF
        note_file_path = get_notes(file_path)
        pdf_file_path = pdf_maker(note_file_path)

        # Read the PDF content
        with open(pdf_file_path, "rb") as f:
            pdf_data = f.read()

        # Clean up temporary files
        os.remove(file_path)
        os.remove(note_file_path)
        os.remove(pdf_file_path)

        headers = {
            'Content-Disposition': f'attachment; filename="notes.pdf"'
        }

        return Response(content=pdf_data, media_type="application/pdf", headers=headers)

    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        raise HTTPException(status_code=500, detail="Error processing audio")


