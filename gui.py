# gui.py

import cmd
import tkinter as tk
from tkinter import messagebox
import time
import random
import threading
import queue
import math
from unicodedata import digit

# ---------- CONFIG USB CDC ----------
SERIAL_BAUD = 9600
PORT = "COM6"             # ajuste si besoin
SERIAL_TIMEOUT = 1.0      # s

# ---------- Serial (thread + file d’événements) ----------
ser = None
serial_q = queue.Queue()

def serial_worker(port):
    """Thread lecteur série: lit, reconstitue des lignes ASCII, pousse ('LINE', '...') dans la file."""
    global ser
    try:
        import serial
        ser = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
    except Exception as e:
        serial_q.put(("ERR", f"Impossible d’ouvrir {port}: {e}"))
        return

    serial_q.put(("INFO", f"Connecté à {port}"))
    buf = ""
    while True:
        try:
            chunk = ser.read(ser.in_waiting or 1)
            if not chunk:
                continue
            try:
                buf += chunk.decode("utf-8", errors="ignore")
            except Exception:
                continue
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                serial_q.put(("LINE", line.strip()))
        except Exception as e:
            serial_q.put(("ERR", f"Erreur lecture série: {e}"))
            break

# ---------- Jeu (paramètres) ----------
WIDTH, HEIGHT = 1000, 600   # Taille fenêtre
GROUND_Y = HEIGHT - 40     # Hauteur du sol
BIRD_X = 200               # Position horizontale de l’oiseau
GRAVITY = 0.45
FLAP_VY = -7.0
PIPE_SPEED = 2.4
PIPE_GAP = 130              # Écartement vertical entre les tuyaux
PIPE_SPACING = 260          # Espace entre les tuyaux


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FLAPPIC-BIRD – Défense 1")
        self.resizable(False, False)
        self.geometry(f"{WIDTH}x{HEIGHT}")
        self.state_mgr = StateManager(self)
        self.after(50, self.poll_serial_events)
        self.after(120, self.state_mgr.start.show)

    def poll_serial_events(self):
        while True:
            try:
                typ, payload = serial_q.get_nowait()
            except queue.Empty:
                break
            if typ == "INFO":
                self.state_mgr.set_status(payload)
            elif typ == "ERR":
                self.state_mgr.set_status(payload)
            elif typ == "LINE":
                self.state_mgr.on_serial_line(payload)
        self.after(15, self.poll_serial_events)

class StateManager:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.status_str = tk.StringVar(value="USB: non connecté")
        self.footer = tk.Label(root, textvariable=self.status_str, anchor="w")
        self.footer.place(x=5, y=HEIGHT-18, width=WIDTH-10, height=16)

        self.start = StartScreen(root, self)
        self.menu = MenuScreen(root, self)
        self.game = GameScreen(root, self)
        self.instructions = InstructionsScreen(root, self)

        self.last_replay = None
        self.goto_start()

    def set_status(self, msg):
        self.status_str.set(msg)

    def on_serial_line(self, line: str):
        print("SERIAL >", line)
    
        # Ignorer toutes les commandes série pendant le replay
        if getattr(self.game, "replaying", False):
            return
        
        cmd = line.strip().upper()

        if cmd.startswith("FLAP"):
            self.game.external_flap()
        elif cmd.startswith("DEAD"):
            self.game.force_game_over()
        elif cmd in ("UP", "DOWN", "SELECT", "BACK"):
            self.handle_menu_command(cmd)

    def handle_menu_command(self, cmd):
        """Navigation menu via commandes série UP/DOWN/SELECT/BACK"""
        if self.start.frame.winfo_ismapped():
            if cmd == "SELECT":
                self.goto_menu()

        elif self.menu.frame.winfo_ismapped():
        # On pilote le sous-menu mode directement si ouvert
            if self.menu.mode_window and self.menu.mode_window.winfo_exists():
                self.menu.handle_mode_input(cmd)
            else:
                self.menu.handle_input(cmd)

        elif self.instructions.frame.winfo_ismapped():
            if cmd == "BACK":
                self.goto_menu()

        elif self.game.frame.winfo_ismapped():
            if cmd == "BACK":
                self.goto_menu()

    # --- Navigation ---
    def goto_start(self):
        self.hide_all()
        self.start.show()

    def goto_menu(self):
        self.hide_all()
        self.menu.show()

    def goto_instructions(self):
        self.hide_all()
        self.instructions.show()

    def goto_game(self, replay_script=None, speedup=1.0):
        self.hide_all()
        self.game.show()
        self.game.start_game(replay_script=replay_script, speedup=speedup)

    def hide_all(self):
        for w in (self.start, self.menu, self.game, self.instructions):
            w.hide()

class StartScreen:
    def __init__(self, root, mgr: StateManager):
        self.root, self.mgr = root, mgr
        self.frame = tk.Frame(root, bg="#0a0a0a")
        self.lbl = tk.Label(self.frame, text="PRESS START", fg="white", bg="#0a0a0a",
                            font=("Helvetica", 26, "bold"))
        self.btn = tk.Button(self.frame, text="Start", command=self.mgr.goto_menu)
        self._blink_on = True
        self._blink_job = None

    def show(self):
        self.frame.place(x=0, y=0, width=WIDTH, height=HEIGHT-18)
        self.lbl.place(relx=0.5, rely=0.45, anchor="center")
        self.btn.place(relx=0.5, rely=0.6, anchor="center")
        self._schedule_blink()

    def hide(self):
        if self._blink_job:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None
        self.frame.place_forget()

    def _schedule_blink(self):
        if self._blink_on:
            self.lbl.place(relx=0.5, rely=0.45, anchor="center")
        else:
            self.lbl.place_forget()
        self._blink_on = not self._blink_on
        self._blink_job = self.root.after(500, self._schedule_blink)

class MenuScreen:
    def __init__(self, root, mgr: StateManager):
        self.root, self.mgr = root, mgr
        self.frame = tk.Frame(root, bg="#111")

        title = tk.Label(self.frame, text="Menu", fg="white", bg="#111", font=("Helvetica", 20, "bold"))
        title.pack(pady=14)

        self.buttons = [
            tk.Button(self.frame, text="Play", command=self.open_mode_menu),
            tk.Button(self.frame, text="Instructions", command=self.mgr.goto_instructions),
            #tk.Button(self.frame, text="Replay (dernier run)", command=self._replay),
            tk.Button(self.frame, text="Replay ", command=self._replay_fast),
            tk.Button(self.frame, text="Back", command=self.mgr.goto_start)
        ]
        for b in self.buttons:
            b.pack(pady=6)

        self.selected_index = 0
        self.highlight_selection()
        self.mode_window = None

    def handle_input(self, cmd: str):
        """Navigation via boutons physiques"""
        if cmd == "UP":
            self.selected_index = (self.selected_index - 1) % len(self.buttons)
            self.highlight_selection()
        elif cmd == "DOWN":
            self.selected_index = (self.selected_index + 1) % len(self.buttons)
            self.highlight_selection()
        elif cmd == "SELECT":
            self.buttons[self.selected_index].invoke()
        elif cmd == "BACK":
            self.mgr.goto_start()

    def highlight_selection(self):
        """Affiche un curseur visuel sur le bouton sélectionné"""
        for i, b in enumerate(self.buttons):
            if i == self.selected_index:
                b.config(bg="#3399FF", fg="white")
            else:
                b.config(bg="#222", fg="white")

    def handle_mode_input(self, cmd: str):
        """Navigation série dans le sous-menu des modes"""
        if not self.mode_window:
            return
        if cmd == "UP":
            self.mode_index = (self.mode_index - 1) % len(self.mode_buttons)
            self.highlight_mode_selection()
        elif cmd == "DOWN":
            self.mode_index = (self.mode_index + 1) % len(self.mode_buttons)
            self.highlight_mode_selection()
        elif cmd == "SELECT":
            self.mode_buttons[self.mode_index].invoke()
        elif cmd == "BACK":
            self.mode_window.destroy()

    def highlight_mode_selection(self):
        """Met en surbrillance le bouton sélectionné """
        for i, b in enumerate(self.mode_buttons):
            if i == self.mode_index:
                b.config(bg="#3399FF", fg="white")
            else:
                b.config(bg="#333", fg="white")

    def open_mode_menu(self):
        """Sous-menu pour choisir le mode de contrôle (TS7)."""
        if self.mode_window and tk.Toplevel.winfo_exists(self.mode_window):
            self.mode_window.lift()
            return

        self.mode_window = tk.Toplevel(self.root)
        self.mode_window.title("Select Game Mode")
        self.mode_window.geometry("420x320")
        self.mode_window.resizable(False, False)
        self.mode_window.configure(bg="#222")

        tk.Label(self.mode_window, text="Select a control mode:",
                 fg="white", bg="#222", font=("Helvetica", 14, "bold")).pack(pady=12)

        # ---- Quatre modes demandés dans TS7 ----
        self.mode_buttons = [
            tk.Button(self.mode_window, text="1 – Digital Encoder (ASM)",
                      width=30, command=lambda: self.start_mode("ENCODER")),
            tk.Button(self.mode_window, text="2 – Push Button (ASM)",
                      width=30, command=lambda: self.start_mode("BUTTON")),
            tk.Button(self.mode_window, text="3 – Ultrasound Sensor (ASM)",
                      width=30, command=lambda: self.start_mode("ULTRASOUND")),
            tk.Button(self.mode_window, text="4 – IR Distance Click (C)",
                      width=30, command=lambda: self.start_mode("IR")),
            tk.Button(self.mode_window, text="Cancel", width=30,
                      command=self.mode_window.destroy)
        ]
        for b in self.mode_buttons:
            b.pack(pady=6)

        self.mode_index = 0
        self.highlight_mode_selection()

    def start_mode(self, mode_name: str):
        """Notifie le PIC (si connecté) du mode sélectionné puis lance la partie."""
        self.mgr.set_status(f"Mode sélectionné : {mode_name}")
    
        # Mapping des modes vers chiffres
        mode_to_digit = {
            "ENCODER": "1",
            "BUTTON": "2", 
            "ULTRASOUND": "3",
            "IR": "4"
        }
    
        digit = mode_to_digit.get(mode_name, "5")  # 5 pour Cancel
    
        if ser:
            try:
                # Envoyer le chiffre correspondant au mode
                ser.write(f"{digit}\n".encode("utf-8"))
                print(f"Mode envoyé au PIC: {digit}")  # Debug
            except Exception as e:
                print(f"Erreur envoi mode: {e}")
    
        if self.mode_window:
            self.mode_window.destroy()
    
        # Lancer le jeu seulement si ce n'est pas Cancel
        if digit != "5":
            self.mgr.goto_game()

    """def _replay(self):
        if not self.mgr.last_replay:
            messagebox.showinfo("Replay", "Pas encore de partie enregistrée.")
            return
        self.mgr.goto_game(replay_script=self.mgr.last_replay, speedup=1.0)"""

    def _replay_fast(self):
        """Mode replay accéléré x2 """
        if not self.mgr.last_replay:
            messagebox.showinfo("Replay", "Pas encore de partie enregistrée.")
            return
        # ⬇️ change 3.0 -> 2.0
        self.mgr.goto_game(replay_script=self.mgr.last_replay, speedup=2.0)


    def show(self):
        self.frame.place(x=0, y=0, width=WIDTH, height=HEIGHT-18)

    def hide(self):
        self.frame.place_forget()

class InstructionsScreen:
    def __init__(self, root, mgr):
        self.root, self.mgr = root, mgr
        self.frame = tk.Frame(root, bg="#161616")
        txt = ("Objectif: passer entre les tuyaux.\n"
               "- Le microcontrôleur envoie 'FLAP' via USB en fonction du mode de jeu sélectionné.\n"
               "- La GUI gère la gravité et l'affichage.\n"
               "- Menu: Play / Instructions / Replay")
        tk.Label(self.frame, text=txt, fg="white", bg="#161616", justify="left").pack(padx=12, pady=12)
        tk.Button(self.frame, text="Back", command=self.mgr.goto_menu).pack(pady=8)

    def show(self):
        self.frame.place(x=0, y=0, width=WIDTH, height=HEIGHT-18)

    def hide(self):
        self.frame.place_forget()

class GameScreen:
    def __init__(self, root, mgr: StateManager):
        self.root, self.mgr = root, mgr
        self.frame = tk.Frame(root, bg="#222")
        self.canvas = tk.Canvas(self.frame, width=WIDTH, height=HEIGHT, bg="#87CEEB", highlightthickness=0)
        self.lbl = tk.Label(self.frame, text="", anchor="w")
        self.canvas.pack()
        self.lbl.place(x=6, y=4)

        # état jeu
        self.running = False
        self.bird_y = 140
        self.bird_vy = 0.0
        self.pipes = []
        self.score = 0
        self.t0 = 0.0
        self.loop_job = None

        # replay & horloge deterministe
        self.replaying = False
        self.fixed_dt = 1.0 / 60.0
        self.accum = 0.0
        self.last_time = 0.0
        self.play_time = 0.0
        self.tick = 0                 # numéro de frame (physique)
        self.pending_flaps = 0        # flaps en attente d’application au prochain step
        self.last_flap_time = 0.0     # anti-doublon input

        # enregistrement / replay
        self.recorded_frames = []     # liste d'indices de frames (ticks)
        self.replay_frames = []       # frames à rejouer
        self.replay_ptr = 0
        self.run_seed = None
        self.rng = None               # RNG dédié aux tuyaux

        # décor
        self.ground_offset = 0.0
        self.clouds = []
        self.init_background()

        # debug clavier
        self.root.bind("<space>", lambda e: self.external_flap())

    def show(self):
        self.frame.place(x=0, y=0, width=WIDTH, height=HEIGHT-18)

    def hide(self):
        self.stop_loop()
        self.frame.place_forget()

    # ---------- fond & rendu ----------
    def init_background(self):
        self.sky_bands = [
            ("#7EC8FF", 0, int(HEIGHT*0.30)),
            ("#74C1FF", int(HEIGHT*0.30), int(HEIGHT*0.55)),
            ("#6BB8FF", int(HEIGHT*0.55), GROUND_Y),
        ]
        rng = random.Random(42)  # RNG visuelle, sans effet gameplay
        self.clouds = []
        for _ in range(6):
            x = rng.randint(0, WIDTH)
            y = rng.randint(20, 120)
            r = rng.randint(14, 24)
            n = rng.randint(3, 5)
            dx = rng.uniform(0.2, 0.6)  # vitesses variées pour un effet de profondeur
            self.clouds.append([x, y, r, n, dx])

    def draw_sky(self):
        for col, y1, y2 in self.sky_bands:
            self.canvas.create_rectangle(0, y1, WIDTH, y2, fill=col, width=0, tags="bg")
        for i, (x, y, r, n, dx) in enumerate(self.clouds):
            for k in range(n):
                self.canvas.create_oval(x + k*r*0.8, y + (-1 if k%2==0 else 3),
                                        x + k*r*0.8 + r*2, y + r*2,
                                        fill="white", outline="", tags="bg")
            self.clouds[i][0] = x - dx
            if self.clouds[i][0] < -60:
                self.clouds[i][0] = WIDTH + 30

    def draw_ground(self):
        self.ground_offset = (self.ground_offset + PIPE_SPEED*1.0) % 20
        # terre
        self.canvas.create_rectangle(0, GROUND_Y, WIDTH, HEIGHT, fill="#8B5A2B", width=0, tags="ground")
        # herbe
        self.canvas.create_rectangle(0, GROUND_Y-6, WIDTH, GROUND_Y, fill="#52B34D", width=0, tags="ground")
        # relief défilant
        step = 20
        x0 = -self.ground_offset
        for x in range(int(x0), WIDTH+step, step):
            self.canvas.create_rectangle(x, GROUND_Y-6, x+8, GROUND_Y, fill="#4AA646", outline="", tags="ground")

    def draw_bird(self):
        self.canvas.delete("bird")
        cx, cy = BIRD_X, int(self.bird_y)
        # aile battante (sinus) + léger effet lié à la vitesse verticale
        flap_phase = (time.perf_counter() * 10.0) % (2.0 * math.pi)
        wing_offset = int(4 * (1 + math.sin(flap_phase)) - 0.4 * self.bird_vy)

        # corps (32x24) -> demi-axes 16/12
        self.canvas.create_oval(cx-16, cy-12, cx+16, cy+12,
                                fill="#FFD93D", outline="#C49A00", width=2, tags="bird")
        # ventre clair
        self.canvas.create_oval(cx-10, cy-6, cx+10, cy+8,
                                fill="#FFE98A", outline="", tags="bird")
        # aile
        self.canvas.create_oval(cx-14, cy-4+wing_offset, cx-2, cy+6+wing_offset,
                                fill="#FFC83A", outline="#C49A00", width=1, tags="bird")
        # œil
        self.canvas.create_oval(cx+2, cy-8, cx+10, cy, fill="white", outline="#222", width=1, tags="bird")
        self.canvas.create_oval(cx+6, cy-4, cx+8, cy-2, fill="#222", outline="#222", tags="bird")
        # bec (dépasse à +22)
        self.canvas.create_polygon(cx+10, cy-2, cx+22, cy+2, cx+10, cy+6,
                                   fill="#FF8C1A", outline="#C56000", width=1, tags="bird")

    def draw_pipe_pair(self, x, gy):
        # tuyau haut
        body_top_y2 = gy
        self.canvas.create_rectangle(x, 0, x+60, body_top_y2, fill="#4EC04E", outline="#2D7F2D", width=2, tags="pipe")
        # lèvre haut (cap arrondi)
        self.canvas.create_rectangle(x-4, gy-18, x+64, gy, fill="#66D066", outline="#2D7F2D", width=2, tags="pipe")
        self.canvas.create_oval(x-6, gy-22, x+6, gy-10, fill="#66D066", outline="#2D7F2D", width=2, tags="pipe")
        self.canvas.create_oval(x+54, gy-22, x+66, gy-10, fill="#66D066", outline="#2D7F2D", width=2, tags="pipe")

        # tuyau bas
        body_bot_y1 = gy + PIPE_GAP
        self.canvas.create_rectangle(x, body_bot_y1, x+60, GROUND_Y, fill="#4EC04E", outline="#2D7F2D", width=2, tags="pipe")
        # lèvre bas (cap arrondi)
        self.canvas.create_rectangle(x-4, gy+PIPE_GAP, x+64, gy+PIPE_GAP+18, fill="#66D066", outline="#2D7F2D", width=2, tags="pipe")
        self.canvas.create_oval(x-6, gy+PIPE_GAP+4, x+6, gy+PIPE_GAP+16, fill="#66D066", outline="#2D7F2D", width=2, tags="pipe")
        self.canvas.create_oval(x+54, gy+PIPE_GAP+4, x+66, gy+PIPE_GAP+16, fill="#66D066", outline="#2D7F2D", width=2, tags="pipe")

        # ombrage simple
        self.canvas.create_rectangle(x+56, 0, x+60, body_top_y2, fill="#3FA43F", outline="", tags="pipe")
        self.canvas.create_rectangle(x+56, body_bot_y1, x+60, GROUND_Y, fill="#3FA43F", outline="", tags="pipe")

    def draw_pipes(self):
        self.canvas.delete("pipe")
        for p in self.pipes:
            self.draw_pipe_pair(p["x"], p["gap_y"])

    def draw_scene(self):
        self.canvas.delete("all")
        self.draw_sky()
        self.draw_pipes()
        self.draw_ground()
        self.draw_bird()
        # HUD score avec ombre
        self.canvas.create_text(WIDTH/2+1, 36+1, text=str(self.score), font=("Helvetica", 26, "bold"),
                                fill="#333333", tags="hud")
        self.canvas.create_text(WIDTH/2, 36, text=str(self.score), font=("Helvetica", 26, "bold"),
                                fill="#FFFFFF", tags="hud")

    # ---------- logique jeu ----------
    def start_game(self, replay_script=None, speedup=1.0):
        # RNG dédiée au gameplay
        if replay_script:
            self.run_seed = replay_script.get("seed", 123456789)
            self.rng = random.Random(self.run_seed)
            random.seed(0xDEADBEEF)  # neutralise le global
            self.replay_frames = list(replay_script.get("frames", []))
            if not self.replay_frames and replay_script.get("events"):
                self.replay_frames = [max(0, int(t / self.fixed_dt + 0.5)) for (t, kind) in replay_script["events"] if kind == "FLAP"]
            self.replay_ptr = 0
            self.replaying = True
        else:
            self.run_seed = random.randrange(1 << 30)
            self.rng = random.Random(self.run_seed)
            random.seed(0xDEADBEEF)
            self.replay_frames = []
            self.replay_ptr = 0
            self.replaying = False

        self.reset_state()
        self.running = True
        self.t0 = time.perf_counter()
        self.last_time = self.t0
        self.accum = 0.0
        self.play_time = 0.0
        self.tick = 0
        self.pending_flaps = 0
        self.replay_speed = speedup if replay_script else 1.0
        self.loop()

    def reset_state(self):
        self.canvas.delete("all")
        self.running = False
        self.bird_y = 140
        self.bird_vy = 0.0
        self.pipes = []
        self.score = 0
        self.recorded_frames = []
        self.ground_offset = 0.0
        self.draw_sky()
        self.draw_ground()
        self.draw_bird()
        self.spawn_initial_pipes()
        self.lbl.config(text="Score: 0")

    def stop_loop(self):
        if self.loop_job:
            self.root.after_cancel(self.loop_job)
            self.loop_job = None

    def set_status(self, s):
        self.mgr.set_status(s)

    def spawn_initial_pipes(self):
        x = WIDTH + 40
        for _ in range(3):
            self.add_pipe(x)
            x += PIPE_SPACING

    def add_pipe(self, x):
        gap_y = self.rng.randint(70, HEIGHT-70-PIPE_GAP)
        self.pipes.append({"x": x, "gap_y": gap_y, "scored": False})

    # ----- Physique déterministe -----
    def step_physics(self, dt):
        # appliquer les flaps en attente AU PAS DE PHYSIQUE
        if self.pending_flaps > 0:
            self.bird_vy = FLAP_VY
            self.pending_flaps -= 1

        scale = dt * 60.0
        self.bird_vy += GRAVITY * scale
        self.bird_y += self.bird_vy * scale

        for p in self.pipes:
            p["x"] -= PIPE_SPEED * scale

        if self.pipes and self.pipes[-1]["x"] < WIDTH - PIPE_SPACING:
            self.add_pipe(WIDTH + 40)
        self.pipes = [p for p in self.pipes if p["x"] + 60 > 0]

    def external_flap(self):
        now = time.perf_counter()
        if now - self.last_flap_time < 0.12:  # anti-doublon humain
            return
        self.last_flap_time = now

        # Enregistre au format FRAME-PERFECT : au prochain step
        target_tick = self.tick + 1
        if not self.replaying:
            self.recorded_frames.append(target_tick)
        self.pending_flaps += 1

    def force_game_over(self):
        if self.running:
            self.game_over()

    def loop(self):
        if not self.running:
            return

        now = time.perf_counter()
        dt = now - self.last_time
        self.last_time = now
        if dt > 0.05:
            dt = 0.05

        # Accélère uniquement en replay : on consomme le temps 2× plus vite
        speed = self.replay_speed if self.replaying else 1.0
        self.accum += dt * speed

        # Pas fixe 1/60 s => gameplay identique au run d'origine
        while self.accum >= self.fixed_dt:
            if self.replaying and self.replay_ptr < len(self.replay_frames):
                if self.replay_frames[self.replay_ptr] == self.tick + 1:
                    self.pending_flaps += 1
                    self.replay_ptr += 1

            self.step_physics(self.fixed_dt)
            self.play_time += self.fixed_dt
            self.tick += 1

            if self.check_collision():
                self.game_over()
                return
            self.update_score()

            self.accum -= self.fixed_dt

        # Rendu à ~60 FPS 
        self.draw_scene()
        self.loop_job = self.root.after(16, self.loop)

    def update_score(self):
        for p in self.pipes:
            if not p["scored"] and p["x"] + 60 < BIRD_X:
                p["scored"] = True
                self.score += 1
                self.lbl.config(text=f"Score: {self.score}")

                # Envoyer commande buzzer score au PIC
                if ser:
                    try:
                        ser.write(b"BUZZER_SCORE\n")
                        print("Buzzer: Score")  # Debug
                    except Exception as e:
                        print(f"Erreur envoi buzzer score: {e}")


    # HITBOX 
    def check_collision(self):
        bird_top = self.bird_y - 12
        bird_bottom = self.bird_y + 12
        bird_left = BIRD_X - 14
        bird_right = BIRD_X + 18  

        # collisions écran (haut/bas)
        if bird_bottom >= GROUND_Y or bird_top <= 0:
            return True

        # collisions tuyaux
        for p in self.pipes:
            x1, x2 = p["x"], p["x"] + 60
            gap_top = p["gap_y"]
            gap_bottom = p["gap_y"] + PIPE_GAP

            # overlap horizontal ?
            if bird_right > x1 and bird_left < x2:
                # si le haut ou le bas de l’oiseau sort du gap -> collision
                if bird_top < gap_top or bird_bottom > gap_bottom:
                    return True
        return False

    def game_over(self):
        self.running = False
        self.stop_loop()

        # Envoyer commande buzzer game over au PIC
        if ser:
            try:
                ser.write(b"BUZZER_GAMEOVER\n")
                print("Buzzer: Game Over")  # Debug
            except Exception as e:
                print(f"Erreur envoi buzzer game over: {e}")

        # Sauvegarde frame-perfect
        self.mgr.last_replay = {
            "seed": self.run_seed,
            "frames": list(self.recorded_frames),
        }
        self.canvas.create_text(WIDTH/2, HEIGHT/2, text="GAME OVER", font=("Helvetica", 24, "bold"), fill="red")
        self.canvas.create_text(WIDTH/2, HEIGHT/2+30, text=f"Score: {self.score}", font=("Helvetica", 16), fill="black")
    
        # Reset du flag replay pour éviter le blocage
        self.replaying = False
    
        self.root.after(1500, self.mgr.goto_menu)

def main():
    app = App()
    port = PORT
    if not port:
        app.state_mgr.set_status("USB: port introuvable – configurez PORT dans le code.")
    else:
        th = threading.Thread(target=serial_worker, args=(port,), daemon=True)
        th.start()
    app.mainloop()

if __name__ == "__main__":
    main()