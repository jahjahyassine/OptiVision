import asyncio
import time 
# On importe le moteur Google que vous avez choisi
from audio.tts_engine.google_tts import GoogleTTS 

class AudioOutputHandler: 
    def __init__(self): 
        # Initialisation du moteur Google TTS
        self.tts = GoogleTTS() 
        # Création d'une file d'attente asynchrone qui trie par priorité
        self._queue = asyncio.PriorityQueue() 
        # Dictionnaire pour éviter de répéter le même message trop vite
        self._cooldowns = {} 
        # État pour savoir si la voix est occupée
        self._speaking = False 
        
    async def speak(self, message: str, priority: int = 5): 
        """
        Reçoit un texte, vérifie sa priorité et l'ajoute à la file d'attente.
        Priorité 1 = Urgent (Obstacle), Priorité 5 = Info (Texte lu).
        """
        if not message:
            return

        # On extrait le premier mot pour le 'cooldown' (ex: éviter de dire "Stop" 10 fois)
        msg_key = message.split()[0].lower() 
        
        # Règle Anti-Spam : pas le même type de message avant 3 secondes
        if time.time() - self._cooldowns.get(msg_key, 0) < 3.0: 
            return 
            
        # GESTION DE L'URGENCE ABSOLUE
        # Si c'est une priorité 1 et que l'IA parle déjà d'un visage ou d'un texte...
        if priority == 1 and self._speaking: 
            print("⚡ Priorité haute détectée ! Interruption du message en cours...")
            self.tts.interrupt() # On coupe immédiatement le son de Google TTS
            
        # On ajoute le message dans la file (le plus petit chiffre sort en premier)
        await self._queue.put((priority, message)) 
        self._cooldowns[msg_key] = time.time() 
        
    async def run_loop(self): 
        """
        C'est la boucle infinie qui surveille la file d'attente et lit les messages.
        Elle doit être lancée dans le main.py.
        """
        print("Système de gestion des priorités audio démarré.")
        while True: 
            # On attend qu'un message arrive dans la file
            priority, msg = await self._queue.get() 
            
            self._speaking = True 
            # On demande au moteur Google de parler (gère le téléchargement + lecture)
            await self.tts.speak_async(msg) 
            self._speaking = False
            
            # Indique à la file que la tâche est terminée
            self._queue.task_done()