import fitz  # PyMuPDF
import httpx
from bs4 import BeautifulSoup
import trafilatura
import os
import logging
import io
from google import genai
from agents.utils import get_gemini_client

logger = logging.getLogger(__name__)

async def process_pdf(file_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        
        # Use common gemini client helper
        client = get_gemini_client()

        for page in doc:
            text += page.get_text()
            
            # If the page contains images and we have a client, ask Gemini to describe any charts or tables
            if client and len(page.get_images()) > 0:
                pix = page.get_pixmap()
                img_bytes = pix.tobytes("png")
                
                try:
                    prompt = "This page contains images, charts, or tables. Please describe them in detail, including any structured data."
                    response = await client.aio.models.generate_content(
                        model='gemini-3-flash-preview',
                        contents=[
                            prompt,
                            {
                                "mime_type": "image/png",
                                "data": img_bytes
                            }
                        ]
                    )
                    if response.text:
                        text += f"\n\n[Image/Chart Description from Page {page.number + 1}]:\n{response.text}\n\n"
                except Exception as img_e:
                    logger.error(f"Error processing image on page {page.number + 1}: {img_e}")

        return text
    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        return f"Error processing PDF: {e}"

async def process_docx(file_bytes: bytes) -> str:
    try:
        f = io.BytesIO(file_bytes)
        doc = Document(f)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return '\n'.join(full_text)
    except Exception as e:
        logger.error(f"Error processing DOCX: {e}")
        return f"Error processing DOCX: {e}"

async def process_image(image_bytes: bytes) -> str:
    try:
        client = get_gemini_client()

        # Prompt from implementation plan
        prompt = (
            "This is a photo related to a business decision (possibly a whiteboard sketch or a chart). "
            "Extract every readable element — text, arrows, boxes, numbers — and describe the relationships and data clearly."
        )

        response = await client.aio.models.generate_content(
            model='gemini-3-flash-preview', # Use flash for vision tasks
            contents=[
                prompt,
                {
                    "mime_type": "image/jpeg", # Defaulting to jpeg, API usually auto-detects or handles it
                    "data": image_bytes
                }
            ]
        )
        return response.text
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        return f"Error processing image: {e}"

async def process_url(url: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            result = trafilatura.extract(downloaded)
            if result:
                return result
        
        # Fallback to BeautifulSoup if trafilatura fails
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            return soup.get_text(separator=' ', strip=True)
    except Exception as e:
        logger.error(f"Error processing URL: {e}")
        return f"Error processing URL: {e}"
