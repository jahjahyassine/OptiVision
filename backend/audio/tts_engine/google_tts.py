import os
import asyncio
from gtts import gTTS
import pygame

class GoogleTTS:
    def __init__(self, lang='fr'):
        """
        Initialise le moteur vocal connecté (Google TTS).
        :param lang: Langue de la voix ('fr' pour français).
        """
        print("Initialisation de la voix connectée au Cloud (Google TTS)...")
        self.lang = lang
        
        # Initialisation du mixeur audio pour pouvoir lire et couper le son
        pygame.mixer.init()
        self._is_playing = False
        print("Google TTS est prêt et connecté !")

    async def speak_async(self, message: str):
        """Génère la voix via internet et la lit."""
        print(f"☁️ 🔊 [Google Cloud] : '{message}'")
        
        audio_file = "temp_alert_google.mp3"
        self._is_playing = True
        
        try:
            # ÉTAPE 1 : Requête réseau vers les serveurs de Google
            # On utilise asyncio.to_thread pour que le téléchargement ne bloque pas la caméra
            def fetch_audio():
                tts = gTTS(text=message, lang=self.lang)
                tts.save(audio_file)
                
            await asyncio.to_thread(fetch_audio)
            
            # ÉTAPE 2 : Si une urgence a annulé la lecture pendant le téléchargement, on s'arrête
            if not self._is_playing:
                return

            # ÉTAPE 3 : Lecture du fichier audio téléchargé
            pygame.mixer.music.load(audio_file)
            pygame.mixer.music.play()
            
            # ÉTAPE 4 : On attend que l'audio se termine... ou qu'il soit interrompu
            while pygame.mixer.music.get_busy() and self._is_playing:
                await asyncio.sleep(0.05) # Vérifie toutes les 50ms
                
        except Exception as e:
            print(f"Erreur de connexion ou de lecture TTS : {e}")
            
        finally:
            # ÉTAPE 5 : Nettoyage (on libère le fichier et on le supprime)
            pygame.mixer.music.unload()
            if os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except OSError:
                    pass

    def interrupt(self):
        """Coupe le son instantanément."""
        self._is_playing = False
        if pygame.mixer.music.get_busy():
            print("🛑 [Audio coupé instantanément pour une urgence !]")
            pygame.mixer.music.stop()