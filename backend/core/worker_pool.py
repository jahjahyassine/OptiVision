import asyncio
from concurrent.futures import ThreadPoolExecutor

class WorkerPool:
    def __init__(self, max_workers=4):
        # On utilise 4 workers pour les 4 modules IA parallèles (YOLO, FaceNet, OCR, MiDaS) [cite: 113, 188]
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    async def run_in_executor(self, func, *args):
        """Exécute une fonction bloquante dans le pool de threads en parallèle."""
        loop = asyncio.get_running_loop()
        # Permet l'exécution concurrente via asyncio [cite: 185]
        return await loop.run_in_executor(self.executor, func, *args)
        
    def shutdown(self):
        """Nettoie le pool de threads à l'arrêt du serveur."""
        self.executor.shutdown(wait=True)

        