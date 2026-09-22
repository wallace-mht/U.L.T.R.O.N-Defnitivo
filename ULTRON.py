import asyncio
import json
import os
import shutil
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime
import threading
import time
import math
import argparse
import speech_recognition as sr
import customtkinter as ctk
import requests
import psutil

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

# ==============================================================================
# CONFIGURAÇÕES DE DIRETÓRIOS E ARQUIVOS LOCAIS
# ==============================================================================
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

PASTA_PROJETO = os.path.expanduser("~/Downloads/U.L.T.R.O.N")
os.makedirs(PASTA_PROJETO, exist_ok=True)

ARQUIVO_MEMORIA = os.path.join(PASTA_PROJETO, "memoria.json")
ARQUIVO_AGENDA = os.path.join(PASTA_PROJETO, "agenda.json")
ARQUIVO_NOTAS = os.path.join(PASTA_PROJETO, "notas.txt")

# ==============================================================================
# CONFIGURAÇÕES DA IA (GEMINI) - FALLBACK INTELIGENTE
# ==============================================================================
# A chave NUNCA fica escrita aqui. Defina no terminal antes de rodar:
#   export GEMINI_API_KEY="sua_chave_aqui"
# Chave gratuita em: https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

INSTRUCAO_SISTEMA_GEMINI = (
    "Você é ULTRON, um assistente pessoal inteligente, direto e educado, que trata "
    "o usuário por 'senhor'. Responda sempre em português do Brasil, com o nível de "
    "detalhe que a pergunta pedir: perguntas simples merecem respostas objetivas, "
    "mas perguntas que pedem explicação, comparação ou detalhes devem ser "
    "respondidas de forma completa e aprofundada, sem cortar informação relevante. "
    "Evite usar markdown, listas com marcadores, emojis ou asteriscos, já que a "
    "resposta pode ser falada em voz alta ou lida em texto simples."
)


def perguntar_gemini(pergunta):
    """Envia uma pergunta para a API do Gemini e retorna a resposta em texto.
    Usada como fallback quando nenhum comando local reconhece o pedido,
    para não gastar tokens do Claude no dia a dia do assistente."""
    if not GEMINI_API_KEY:
        return (
            "A chave da API do Gemini não está configurada, senhor. "
            "Defina a variável de ambiente GEMINI_API_KEY para ativar minha "
            "inteligência geral."
        )

    payload = {
        "system_instruction": {
            "parts": [{"text": INSTRUCAO_SISTEMA_GEMINI}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": pergunta}]}
        ],
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": 4096
        }
    }

    try:
        res = requests.post(
            GEMINI_URL,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": GEMINI_API_KEY
            },
            json=payload,
            timeout=15
        )
        if res.status_code != 200:
            return f"O serviço de inteligência retornou um erro, código {res.status_code}, senhor."

        dados = res.json()
        candidatos = dados.get("candidates", [])
        if not candidatos:
            return "Não consegui gerar uma resposta para isso, senhor."

        partes = candidatos[0].get("content", {}).get("parts", [])
        texto = " ".join(p.get("text", "") for p in partes).strip()
        return texto if texto else "Não consegui gerar uma resposta para isso, senhor."

    except requests.exceptions.Timeout:
        return "O serviço de inteligência demorou demais para responder, senhor."
    except requests.exceptions.RequestException:
        return "Não consegui me conectar ao serviço de inteligência, senhor."
    except Exception:
        return "Ocorreu um erro inesperado ao consultar a inteligência geral, senhor."


def carregar_memoria():
    padrao = {"latitude": -2.9062, "longitude": -41.7757, "cidade": "Parnaíba"}
    if os.path.exists(ARQUIVO_MEMORIA):
        try:
            with open(ARQUIVO_MEMORIA, "r", encoding="utf-8") as f:
                dados = json.load(f)
                for k, v in padrao.items():
                    if k not in dados: dados[k] = v
                return dados
        except Exception:
            pass
    return padrao


# ==============================================================================
# AGENDA - LEITURA E ESCRITA (CORRIGIDO)
# ==============================================================================
def carregar_agenda():
    """Carrega a agenda de forma segura. Se o arquivo não existir, cria um novo.
    Se estiver corrompido, faz um backup em vez de perder os dados."""
    if not os.path.exists(ARQUIVO_AGENDA):
        agenda_inicial = {"compromissos": []}
        salvar_agenda(agenda_inicial)
        return agenda_inicial

    try:
        with open(ARQUIVO_AGENDA, "r", encoding="utf-8") as f:
            dados = json.load(f)
            if not isinstance(dados, dict) or "compromissos" not in dados:
                dados = {"compromissos": dados if isinstance(dados, list) else []}
            return dados
    except json.JSONDecodeError:
        # Arquivo corrompido: faz backup e recomeça do zero em vez de travar
        backup = ARQUIVO_AGENDA + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            shutil.copy(ARQUIVO_AGENDA, backup)
        except Exception:
            pass
        agenda_inicial = {"compromissos": []}
        salvar_agenda(agenda_inicial)
        return agenda_inicial
    except Exception:
        return {"compromissos": []}


def salvar_agenda(dados):
    try:
        with open(ARQUIVO_AGENDA, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def verificar_agenda():
    dados = carregar_agenda()
    compromissos = dados.get("compromissos", [])
    hoje = datetime.now().strftime("%d/%m/%Y")

    # Ignora silenciosamente entradas mal formatadas em vez de quebrar
    compromissos_hoje = [
        c for c in compromissos
        if isinstance(c, dict) and c.get("data") == hoje
    ]

    if not compromissos_hoje:
        return "O senhor não possui compromissos agendados para hoje."

    qtd = len(compromissos_hoje)
    descricoes = "; ".join(c.get("descricao", "sem descrição") for c in compromissos_hoje)
    if qtd == 1:
        return f"O senhor possui 1 compromisso hoje: {descricoes}."
    return f"O senhor possui {qtd} compromissos hoje: {descricoes}."


def acao_cadastrar_compromisso(state):
    """Diálogo por voz para cadastrar um novo compromisso na agenda."""
    falar("Para qual data é o compromisso, senhor?")
    data_falada = ouvir_texto_simples()

    data_final = _normalizar_data_falada(data_falada)
    if not data_final:
        state["resposta"] = "Não entendi a data. Vamos tentar de novo mais tarde, senhor."
        return state

    falar("E qual é a descrição do compromisso?")
    descricao = ouvir_texto_simples()
    if not descricao.strip():
        state["resposta"] = "Não entendi a descrição. Compromisso não foi salvo, senhor."
        return state

    dados = carregar_agenda()
    dados.setdefault("compromissos", []).append({
        "data": data_final,
        "descricao": descricao.strip(),
        "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M")
    })

    if salvar_agenda(dados):
        state["resposta"] = f"Compromisso cadastrado para o dia {data_final}, senhor."
    else:
        state["resposta"] = "Não consegui salvar o compromisso, senhor."
    return state


def _normalizar_data_falada(texto):
    """Converte falas simples como 'hoje', 'amanhã' ou uma data dd/mm/aaaa
    já ditada em formato de data dd/mm/aaaa. Retorna None se não entender."""
    texto = texto.lower().strip()
    hoje = datetime.now()

    if "hoje" in texto:
        return hoje.strftime("%d/%m/%Y")
    if "amanh" in texto:  # cobre "amanhã" com ou sem erro de acentuação do reconhecedor
        from datetime import timedelta
        return (hoje + timedelta(days=1)).strftime("%d/%m/%Y")

    # Tenta extrair um formato dd/mm/aaaa ou dd/mm (assume ano atual) já falado/digitado
    import re
    m = re.search(r"(\d{1,2})[/\- ](\d{1,2})(?:[/\- ](\d{2,4}))?", texto)
    if m:
        dia, mes = int(m.group(1)), int(m.group(2))
        ano = m.group(3)
        ano = int(ano) if ano else hoje.year
        if ano < 100:
            ano += 2000
        try:
            return datetime(ano, mes, dia).strftime("%d/%m/%Y")
        except ValueError:
            return None

    return None


def obter_clima():
    try:
        mem = carregar_memoria()
        url = f"https://api.open-meteo.com/v1/forecast?latitude={mem['latitude']}&longitude={mem['longitude']}&current=temperature_2m,weather_code"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            d = res.json()["current"]
            return f"{d['temperature_2m']}°C em {mem['cidade']}"
    except Exception:
        pass
    return "clima indisponível"

class JarvisHologramGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ULTRON - Unidade Lógica Tecno-Oniciente")
        self.geometry("560x720")
        self.resizable(False, False)

        self.main_frame = ctk.CTkFrame(self, fg_color="#0a0f14", corner_radius=15)
        self.main_frame.pack(padx=15, pady=15, fill="both", expand=True)

        self.title_label = ctk.CTkLabel(
            self.main_frame, text="U.L.T.R.O.N" , 
            font=ctk.CTkFont(size=20, weight="bold"), text_color="#ff0000"
        )
        self.title_label.pack(pady=(10, 5))

        self.canvas_size = 240
        self.canvas = ctk.CTkCanvas(
            self.main_frame, width=self.canvas_size, height=self.canvas_size,
            bg="#0a0f14", highlightthickness=0
        )
        self.canvas.pack(pady=5)

        self.status_label = ctk.CTkLabel(
            self.main_frame, text="INICIALIZANDO SISTEMA...", 
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#ff0000"
        )
        self.status_label.pack(pady=(0, 5))

        self.console_box = ctk.CTkTextbox(
            self.main_frame, width=500, height=180, corner_radius=8,
            font=ctk.CTkFont(family="Consolas", size=11), fg_color="#05080b", text_color="#ff1e00"
        )
        self.console_box.pack(padx=10, pady=5)
        self.console_box.configure(state="disabled")

        self.angulo_anel1 = 0
        self.angulo_anel2 = 0
        self.escala_pulso = 1.0
        self.direcao_pulso = 0.02
        self.estado_atual = "OUVINDO"

        self.animar_holograma()

    def log(self, mensagem):
        self.console_box.configure(state="normal")
        self.console_box.insert("end", f"{mensagem}\n")
        self.console_box.see("end")
        self.console_box.configure(state="disabled")

    def set_estado(self, estado):
        self.estado_atual = estado
        if estado == "OUVINDO":
            self.status_label.configure(text="STATUS: OUVINDO COMANDOS...", text_color="#d43535")
        elif estado == "PROCESSANDO":
            self.status_label.configure(text="STATUS: PROCESSANDO AGENTE...", text_color="#ff9900")
        elif estado == "FALANDO":
            self.status_label.configure(text="STATUS: TRANSMITINDO RESPOSTA...", text_color="#f5e609")

    def animar_holograma(self):
        self.canvas.delete("all")
        cx, cy = self.canvas_size / 2, self.canvas_size / 2

        if self.estado_atual == "FALANDO":
            self.escala_pulso += self.direcao_pulso
            if self.escala_pulso > 1.15 or self.escala_pulso < 0.90:
                self.direcao_pulso *= -1
        else:
            self.escala_pulso = 1.0 + math.sin(time.time() * 3) * 0.03

        r_externo = 95 * self.escala_pulso
        for i in range(8):
            angulo_ini = self.angulo_anel1 + (i * (360 / 8))
            self.canvas.create_arc(
                cx - r_externo, cy - r_externo, cx + r_externo, cy + r_externo,
                start=angulo_ini, extent=30, style="arc", outline="#660000", width=3
            )

        r_medio = 75
        for i in range(6):
            angulo_ini = -self.angulo_anel2 + (i * (360 / 6))
            self.canvas.create_arc(
                cx - r_medio, cy - r_medio, cx + r_medio, cy + r_medio,
                start=angulo_ini, extent=40, style="arc", outline="#ff0000", width=2
            )

        r_esfera = 45 * self.escala_pulso
        self.canvas.create_oval(
            cx - r_esfera, cy - r_esfera, cx + r_esfera, cy + r_esfera,
            outline="#660000", width=2, fill="#100404"
        )
        
        r_nucleo = 12 * self.escala_pulso
        self.canvas.create_oval(
            cx - r_nucleo, cy - r_nucleo, cx + r_nucleo, cy + r_nucleo,
            outline="#e73333", width=1, fill="#290000"
       )

        self.angulo_anel1 = (self.angulo_anel1 + 2) % 360
        self.angulo_anel2 = (self.angulo_anel2 + 3) % 360

        self.after(30, self.animar_holograma)

class DefaultArgs:
    cli = False
    no_voice = False

args = DefaultArgs()
app = None
rec = sr.Recognizer()
rec.energy_threshold = 300
rec.dynamic_energy_threshold = True

async def gerar_audio_edge(texto, arquivo_audio):
    communicate = edge_tts.Communicate(texto, "pt-BR-AntonioNeural")
    await communicate.save(arquivo_audio)

def falar(texto, logar=True):
    if app:
        app.set_estado("FALANDO")
        if logar: app.log(f"ULTRON: {texto}")
    else:
        if logar: print(f"ULTRON: {texto}")
    
    if args.no_voice:
        if app: app.set_estado("OUVINDO")
        return

    audio_file = "resposta.mp3"
    if os.path.exists(audio_file):
        try: os.remove(audio_file)
        except: pass

    if HAS_EDGE_TTS:
        try:
            asyncio.run(gerar_audio_edge(texto, audio_file))
            if os.path.exists(audio_file):
                subprocess.run(["mpg123", "-q", audio_file])
                os.remove(audio_file)
        except Exception as e:
            if app: app.log(f"[Erro de Áudio]: {e}")
            else: print(f"[Erro de Áudio]: {e}")
    
    if app: app.set_estado("OUVINDO")

def ouvir_texto_simples():
    if args.cli:
        try:
            return input("Você (CLI): ").lower()
        except:
            return ""
    with sr.Microphone() as mic:
        rec.adjust_for_ambient_noise(mic, duration=0.2)
        try:
            audio = rec.listen(mic, phrase_time_limit=10)
            return rec.recognize_google(audio, language="pt-BR").lower()
        except:
            return ""

# ==============================================================================
# NÚCLEO DE ESTADOS DO AGENTE (ARQUITETURA MODULAR)
# ==============================================================================
def acao_status_sistema(state):
    try:
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory().percent
        disco = psutil.disk_usage('/').percent
        state["resposta"] = f"CPU em {cpu}%, memória RAM em {mem}%, disco em {disco}%."
    except:
        state["resposta"] = "Erro ao ler status do sistema."
    return state

def acao_controlar_volume(state):
    cmd = state["comando"]
    try:
        if "aumentar" in cmd:
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"])
            state["resposta"] = "Volume aumentado, senhor."
        elif "baixar" in cmd or "diminuir" in cmd:
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"])
            state["resposta"] = "Volume diminuído, senhor."
        elif "mudo" in cmd:
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
            state["resposta"] = "Alternando mudo, senhor."
    except:
        state["resposta"] = "Erro ao controlar o volume."
    return state

def acao_salvar_nota(state):
    cmd = state["comando"]
    conteudo = cmd.replace("anotar", "").replace("lembrete", "").strip()
    try:
        with open(ARQUIVO_NOTAS, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%d/%m/%Y %H:%M')}] {conteudo}\n")
        state["resposta"] = "Nota registrada com sucesso, senhor."
    except:
        state["resposta"] = "Erro ao salvar nota."
    return state

def acao_abrir_pasta(state):
    cmd = state["comando"]
    pastas = {"downloads": "~/Downloads", "documentos": "~/Documentos", "imagens": "~/Imagens", "projetos": PASTA_PROJETO}
    for k, v in pastas.items():
        if k in cmd:
            subprocess.Popen(["xdg-open", os.path.expanduser(v)])
            state["resposta"] = f"Abrindo pasta {k}, senhor."
            return state
    state["resposta"] = "Pasta não encontrada."
    return state

# Nó Central de Decisão (Roteador de Estados)
def no_processador_agente(state):
    cmd = state["comando"].lower()
    state["sucesso"] = True

    if "suspender" in cmd or "dormir" in cmd:
        state["resposta"] = "Entrando em suspensão."
        subprocess.run(["systemctl", "suspend"])
    elif "desligar" in cmd:
        state["resposta"] = "Desligando o computador."
        subprocess.run(["systemctl", "poweroff"])
    elif "sistema" in cmd or "cpu" in cmd or "memória" in cmd:
        return acao_status_sistema(state)
    elif "volume" in cmd or "aumentar" in cmd or "baixar" in cmd or "mudo" in cmd:
        return acao_controlar_volume(state)
    elif "cadastrar compromisso" in cmd or "agendar compromisso" in cmd or "novo compromisso" in cmd:
        return acao_cadastrar_compromisso(state)
    elif "agenda" in cmd or "compromissos" in cmd:
        state["resposta"] = verificar_agenda()
    elif "print" in cmd or "captura" in cmd:
        img_dir = os.path.expanduser("~/Imagens")
        os.makedirs(img_dir, exist_ok=True)
        arq = os.path.join(img_dir, f"print_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        subprocess.run(["gnome-screenshot", "-f", arq])
        state["resposta"] = "Captura de tela realizada."
    elif "anotar" in cmd or "lembrete" in cmd:
        return acao_salvar_nota(state)
    elif "pasta" in cmd:
        return acao_abrir_pasta(state)
    elif "horas" in cmd:
        state["resposta"] = f"Agora são {datetime.now().strftime('%H horas e %M minutos')}."
    elif "clima" in cmd:
        state["resposta"] = f"O clima atual está com {obter_clima()}."
    elif "tocar o terror" in cmd:
        webbrowser.open("https://youtu.be/ZRbLHXhcqZA")
        state["resposta"] = "Abrindo o vídeo para tocar o terror, senhor."
    elif "youtube" in cmd:
        if "pesquisar" in cmd:
            termo = cmd.replace("youtube", "").replace("pesquisar", "").strip()
            webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(termo)}")
            state["resposta"] = f"Buscando {termo} no YouTube."
        else:
            webbrowser.open("https://www.youtube.com")
            state["resposta"] = "Abrindo YouTube."
    elif "brave" in cmd or "navegador" in cmd:
        webbrowser.open("https://www.google.com")
        state["resposta"] = "Abrindo navegador."
    elif "terminal" in cmd:
        subprocess.Popen(["gnome-terminal"])
        state["resposta"] = "Abrindo terminal."
    elif "calculadora" in cmd:
        subprocess.Popen(["gnome-calculator"])
        state["resposta"] = "Abrindo calculadora."
    elif "vscode" in cmd:
        subprocess.Popen(["code"])
        state["resposta"] = "Abrindo VS Code."
    else:
        # Nenhum comando local reconheceu o pedido: usa o Gemini como
        # "cérebro" de propósito geral, sem gastar tokens do Claude.
        state["resposta"] = perguntar_gemini(state["comando"])
        state["sucesso"] = True
        
    return state

def loop_jarvis():
    time.sleep(1)
    status_agenda = verificar_agenda()
    falar(f"Bom dia senhor. O clima está com {obter_clima()}. {status_agenda} Núcleo de agentes locais ativado.")

    while True:
        if app: app.set_estado("OUVINDO")
        
        if args.cli:
            try:
                texto = input("Você (CLI): ").lower()
            except (KeyboardInterrupt, EOFError):
                break
            if not texto.strip():
                continue
        else:
            with sr.Microphone() as mic:
                rec.adjust_for_ambient_noise(mic, duration=0.2)
                try:
                    audio = rec.listen(mic, phrase_time_limit=15)
                except:
                    continue

            try:
                if app: app.set_estado("PROCESSANDO")
                texto = rec.recognize_google(audio, language="pt-BR").lower()
                if app: app.log(f"Você: {texto}")
                else: print(f"Você: {texto}")
            except sr.UnknownValueError:
                continue
            except sr.RequestError:
                if app: app.log("[Erro de Conexão com o Reconhecedor]")
                else: print("[Erro de Conexão com o Reconhecedor]")
                continue

        # Executando o fluxo através do Estado do Agente
        estado_sessao = {"comando": texto, "resposta": "", "sucesso": False}
        estado_atualizado = no_processador_agente(estado_sessao)
        
        falar(estado_atualizado["resposta"])

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ULTRON - Unidade Lógica Tecno-Oniciente (Base de Agentes)")
    parser.add_argument("--cli", "-c", action="store_true", help="Executar em modo CLI (sem interface gráfica)")
    parser.add_argument("--no-voice", action="store_true", help="Desativar síntese/reconhecimento de voz em áudio")
    args = parser.parse_args() 

    if args.cli:
        print("Iniciando ULTRON em modo CLI (Arquitetura de Agentes)...")
        threading.Thread(target=loop_jarvis, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nEncerrando ULTRON...")
    else:
        app = JarvisHologramGUI()
        threading.Thread(target=loop_jarvis, daemon=True).start()
        app.mainloop()