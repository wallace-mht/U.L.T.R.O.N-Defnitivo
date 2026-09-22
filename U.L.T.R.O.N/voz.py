import pyttsx3
import speech_recognition as sr
import time

class GerenciadorVoz:
    def __init__(self):
        self.falando = False
        try:
            # Inicializa o motor de voz de forma segura
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', 160)
            
            # Tenta selecionar uma voz em português
            voices = self.engine.getProperty('voices')
            for voice in voices:
                if "pt" in voice.id.lower() or "portuguese" in voice.id.lower():
                    self.engine.setProperty('voice', voice.id)
                    break
        except Exception as e:
            print(f"[Aviso] Motor de voz inicializado em modo de contingência: {e}")
            self.engine = None

        try:
            self.recognizer = sr.Recognizer()
        except Exception:
            self.recognizer = None

    def falar(self, texto):
        self.falando = True
        if self.engine:
            try:
                self.engine.say(texto)
                self.engine.runAndWait()
            except Exception as e:
                print(f"[Erro ao falar]: {e}")
        else:
            print(f"ULTRON (Modo Texto): {texto}")
        time.sleep(0.3)  # Pequena pausa para estabilizar antes de reabrir o microfone
        self.falando = False

    def ouvir(self):
        if not self.recognizer:
            time.sleep(1)
            return None

        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                while True:
                    if self.falando:
                        time.sleep(0.1)
                        continue
                    
                    audio = self.recognizer.listen(source, timeout=3, phrase_time_limit=5)
                    if self.falando:
                        continue
                    return self.recognizer.recognize_google(audio, language="pt-BR")
        except Exception:
            return None