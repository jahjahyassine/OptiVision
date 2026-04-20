import asyncio

class FrameQueue:
    def __init__(self, maxsize=5):
        # Initialisation avec une taille maximale de 5 [cite: 107]
        self.queue = asyncio.Queue(maxsize=maxsize)

    async def put_nowait(self, frame):
        """Ajoute une image et supprime la plus ancienne si la file est pleine."""
        if self.queue.full():
            try:
                # Politique d'abandon : on retire l'image la plus ancienne [cite: 150, 188]
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        
        # Ajout de la nouvelle image de manière non bloquante [cite: 107]
        self.queue.put_nowait(frame)

    async def get(self):
        """Récupère la prochaine image à traiter."""
        return await self.queue.get()
    
    