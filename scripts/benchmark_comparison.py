#!/usr/bin/env python3
r"""
Benchmark prestazionale tra Architettura Sequenziale (prima) e Architettura Parallela (nuova).
Test sui file in C:\Users\Leo\Desktop\test_dataset_100_documenti
"""
import os
import sys
import time
import asyncio
import httpx
from pathlib import Path
from typing import List, Tuple

# Imposta il percorso del progetto
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.models.database import SessionLocal, get_app_setting
from app.services.ai_service import get_ai_service

DATASET_DIR = Path(r"C:\Users\Leo\Desktop\test_dataset_100_documenti")


def load_dataset() -> List[Tuple[str, bytes, str]]:
    """Carica in memoria tutti i file del dataset di test."""
    files = []
    for f in sorted(DATASET_DIR.glob("*.pdf")):
        if f.is_file():
            files.append((f.name, f.read_bytes(), "application/pdf"))
    for f in sorted(DATASET_DIR.glob("*.jpg")):
        if f.is_file():
            files.append((f.name, f.read_bytes(), "image/jpeg"))
    for f in sorted(DATASET_DIR.glob("*.png")):
        if f.is_file():
            files.append((f.name, f.read_bytes(), "image/png"))
    return files


def benchmark_sequential(files: List[Tuple[str, bytes, str]], ai_service) -> Tuple[float, int, List[dict]]:
    """
    Test 1: Architettura di prima (Sequenziale, uno alla volta).
    Ogni file viene analizzato in serie, attendendo la risposta dell'AI prima di passare al successivo.
    """
    print(f"\n--- [1] AVVIO TEST: ARCHITETTURA DI PRIMA (SEQUENZIALE) ---")
    print(f"Totale documenti da analizzare uno alla volta: {len(files)}")
    start_time = time.perf_counter()

    results = []
    for idx, (filename, content, mime_type) in enumerate(files, 1):
        t_doc_start = time.perf_counter()
        doc = ai_service.extract_document(content, mime_type, filename=filename)
        t_doc_elapsed = time.perf_counter() - t_doc_start
        results.append({
            "filename": filename,
            "title": doc.title,
            "issuer": doc.issuer,
            "amount": doc.amount,
            "elapsed": t_doc_elapsed
        })
        if idx % 10 == 0 or idx == len(files):
            elapsed_so_far = time.perf_counter() - start_time
            print(f"  [Sequenziale] Progresso: {idx}/{len(files)} documenti analizzati ({elapsed_so_far:.1f}s trascorsi)...")

    total_time = time.perf_counter() - start_time
    print(f"--- [1] FINE TEST SEQUENZIALE: {total_time:.2f} secondi ({len(results)} file) ---\n")
    return total_time, len(results), results


async def benchmark_parallel(files: List[Tuple[str, bytes, str]], ai_service, concurrency: int = 8) -> Tuple[float, int, List[dict]]:
    """
    Test 2: Architettura Parallela (8 worker simultanei con httpx.AsyncClient condiviso).
    Tutti i file vengono elaborati contemporaneamente in parallelo saturando la connessione HTTP.
    """
    print(f"\n--- [2] AVVIO TEST: ARCHITETTURA PARALLELA (8 WORKER CONCORRENTI) ---")
    print(f"Totale documenti da analizzare contemporaneamente: {len(files)} (concorrenza: {concurrency})")
    start_time = time.perf_counter()

    semaphore = asyncio.Semaphore(concurrency)
    completed_counter = 0
    results = []

    async with httpx.AsyncClient(
        limits=httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency),
        timeout=60.0
    ) as client:

        async def _process_file(filename: str, content: bytes, mime_type: str) -> dict:
            nonlocal completed_counter
            async with semaphore:
                t0 = time.perf_counter()
                if hasattr(ai_service, "extract_document_async"):
                    doc = await ai_service.extract_document_async(client, content, mime_type, filename=filename)
                else:
                    loop = asyncio.get_running_loop()
                    doc = await loop.run_in_executor(None, ai_service.extract_document, content, mime_type, filename)
                dt = time.perf_counter() - t0
                completed_counter += 1
                if completed_counter % 10 == 0 or completed_counter == len(files):
                    elapsed_so_far = time.perf_counter() - start_time
                    print(f"  [Parallelo] Progresso: {completed_counter}/{len(files)} documenti completati ({elapsed_so_far:.1f}s trascorsi)...")
                return {
                    "filename": filename,
                    "title": doc.title,
                    "issuer": doc.issuer,
                    "amount": doc.amount,
                    "elapsed": dt
                }

        tasks = [_process_file(fn, cnt, mt) for fn, cnt, mt in files]
        results = await asyncio.gather(*tasks)

    total_time = time.perf_counter() - start_time
    print(f"--- [2] FINE TEST PARALLELO: {total_time:.2f} secondi ({len(results)} file) ---\n")
    return total_time, len(results), results


def main():
    if not DATASET_DIR.exists():
        print(f"ERRORE: Cartella dataset non trovata: {DATASET_DIR}")
        sys.exit(1)

    files = load_dataset()
    if not files:
        print(f"ERRORE: Nessun file trovato in {DATASET_DIR}")
        sys.exit(1)

    print("=" * 70)
    print(f"BENCHMARK PRESTAZIONI: DOVE LO AI MESSO")
    print(f"Dataset: {DATASET_DIR} ({len(files)} file caricati)")
    print("=" * 70)

    db = SessionLocal()
    ai_service = get_ai_service(db)
    model_name = getattr(ai_service, "primary_model", "OpenRouter AI")
    print(f"Modello AI attivo: {model_name}")

    # 1. Esegui test Sequenziale
    time_seq, count_seq, _ = benchmark_sequential(files, ai_service)

    # 2. Esegui test Parallelo
    time_par, count_par, _ = asyncio.run(benchmark_parallel(files, ai_service, concurrency=8))

    # 3. Confronto e riepilogo
    speedup = time_seq / time_par if time_par > 0 else 0
    time_saved = time_seq - time_par
    pct_saved = (time_saved / time_seq * 100) if time_seq > 0 else 0

    print("\n" + "=" * 70)
    print("RISULTATI FINALI DEL BENCHMARK COMPARATIVO")
    print("=" * 70)
    print(f"• Documenti analizzati:           {len(files)}")
    print(f"• Tempo Architettura di Prima:    {time_seq:.2f} secondi ({time_seq / 60:.1f} minuti)")
    print(f"  -> Media per documento:         {time_seq / len(files):.2f}s / doc")
    print(f"• Tempo Architettura Parallela:   {time_par:.2f} secondi ({time_par / 60:.1f} minuti)")
    print(f"  -> Media per documento:         {time_par / len(files):.2f}s / doc")
    print(f"• FATTORE DI VELOCITÀ (Speedup):  {speedup:.2f}x PIÙ VELOCE")
    print(f"• TEMPO RISPARMIATO:              {time_saved:.2f} secondi in meno ({pct_saved:.1f}% più rapido)")
    print("=" * 70)


if __name__ == "__main__":
    main()
