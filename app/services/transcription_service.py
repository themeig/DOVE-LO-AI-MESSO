"""
Servizio di Trascrizione Audio e Speech-to-Text per 'Dove lo AI messo'.

Fornisce trascrizione accurata in lingua italiana per messaggi vocali:
1. SpeechRecognition (Google STT in italiano, gratuito, senza limiti di credito)
2. Normalizzazione automatica in WAV PCM 16kHz mono (con wave standard o ffmpeg)
3. Fallback Gemini Multimodal se configurata GEMINI_API_KEY
4. Gestione robusta del silenzio e dell'audio incomprensibile
"""
import io
import wave
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def ensure_wav_pcm(audio_bytes: bytes, audio_format: str = "wav") -> Optional[bytes]:
    """
    Assicura che i byte audio siano in formato WAV PCM standard leggibile da speech_recognition.AudioFile.
    Se l'audio non è già WAV PCM conforme, usa ffmpeg per la conversione a 16kHz mono 16-bit.
    """
    if not audio_bytes or len(audio_bytes) < 12:
        return None

    # Verifica se è un WAV PCM valido
    if audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:16]:
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                # Se è leggibile dal modulo wave standard di Python, è valido
                if wf.getnframes() > 0:
                    return audio_bytes
        except Exception:
            pass

    # Conversione tramite ffmpeg se disponibile nel sistema
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", "pipe:0",
                "-f", "wav",
                "-ar", "16000",
                "-ac", "1",
                "-acodec", "pcm_s16le",
                "pipe:1"
            ],
            input=audio_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=True
        )
        if proc.stdout and proc.stdout.startswith(b"RIFF") and len(proc.stdout) > 44:
            return proc.stdout
    except Exception as conv_err:
        logger.warning(f"Conversione audio non riuscita tramite ffmpeg: {conv_err}")

    # Fallback: restituisci i byte originali se già iniziano per RIFF
    if audio_bytes.startswith(b"RIFF"):
        return audio_bytes

    return None


def transcribe_audio(audio_bytes: bytes, audio_format: str = "wav", language: str = "it-IT") -> Optional[str]:
    """
    Trascrive l'audio in testo italiano.
    Restituisce:
    - Stringa trascritta se il parlato è stato riconosciuto (es. 'Dov'è il passaporto?')
    - '' (stringa vuota) se l'audio è silenzioso o non contiene parole comprensibili
    - None se si è verificato un errore critico irrecuperabile
    """
    if not audio_bytes or len(audio_bytes) < 44:
        logger.info("Audio vuoto o troppo breve per la trascrizione.")
        return ""

    # 1. Normalizza in WAV PCM
    wav_bytes = ensure_wav_pcm(audio_bytes, audio_format)
    if not wav_bytes:
        logger.warning("Impossibile convertire l'audio in WAV PCM per la trascrizione.")
        return ""

    # 2. Metodo primario: SpeechRecognition (Google STT in italiano)
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        r.energy_threshold = 280
        r.dynamic_energy_threshold = True

        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio_data = r.record(source)

        text = r.recognize_google(audio_data, language=language)
        if text and text.strip():
            clean = text.strip()
            logger.info(f"Trascrizione vocale riuscita (Google STT): '{clean}'")
            return clean
    except sr.UnknownValueError:
        logger.info("Nessuna parola comprensibile rilevata nell'audio (silenzio o rumore di fondo).")
        return ""
    except sr.RequestError as req_err:
        logger.warning(f"SpeechRecognition errore di rete o servizio: {req_err}")
    except Exception as e:
        logger.warning(f"Errore generico durante la trascrizione SpeechRecognition: {e}")

    # 3. Metodo secondario: Fallback Google Gemini Multimodal se configurata GEMINI_API_KEY
    try:
        from app.config import get_settings
        settings = get_settings()
        if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip():
            import httpx
            import base64
            b64 = base64.b64encode(wav_bytes).decode("utf-8")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.GEMINI_API_KEY.strip()}"
            body = {
                "contents": [{
                    "parts": [
                        {
                            "text": "Trascrivi con precisione le parole pronunciate in italiano in questo audio. "
                                    "Restituisci ESCLUSIVAMENTE il testo trascritto, senza commenti o spiegazioni aggiuntive. "
                                    "Se l'audio è muto o silenzioso, restituisci solo una stringa vuota."
                        },
                        {"inline_data": {"mime_type": "audio/wav", "data": b64}}
                    ]
                }]
            }
            res = httpx.post(url, json=body, timeout=15.0)
            if res.status_code == 200:
                data = res.json()
                cand = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if cand and cand.strip():
                    clean = cand.strip()
                    logger.info(f"Trascrizione vocale riuscita (Gemini): '{clean}'")
                    return clean
                return ""
    except Exception as gem_err:
        logger.warning(f"Fallback trascrizione Gemini non riuscito: {gem_err}")

    return ""
