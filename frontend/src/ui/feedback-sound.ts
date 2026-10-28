// 關鍵回饋音效：全部用 Web Audio 即時合成，沒有音檔；音量低、每個提示不超過 0.6 秒。
// 瀏覽器要求使用者操作後才能發聲，所以第一次點擊或按鍵之前一律靜音。
export type Cue = "click" | "correct" | "incorrect" | "levelUp" | "badge" | "stage" | "cardKnown";

const STORAGE_KEY = "studydy.sound";
type Note = { freq: number; at: number; length: number; type?: OscillatorType; gain?: number; to?: number };

const cues: Record<Cue, Note[]> = {
  click: [{ freq: 880, at: 0, length: 0.04, gain: 0.05 }],
  correct: [{ freq: 659, at: 0, length: 0.14 }, { freq: 880, at: 0.1, length: 0.22 }],
  // 答錯：單一、柔和、往下滑的低音，不用不協和音。
  incorrect: [{ freq: 330, at: 0, length: 0.26, to: 277, gain: 0.07 }],
  levelUp: [{ freq: 523, at: 0, length: 0.14 }, { freq: 659, at: 0.1, length: 0.14 }, { freq: 784, at: 0.2, length: 0.14 }, { freq: 1047, at: 0.3, length: 0.3 }],
  badge: [{ freq: 784, at: 0, length: 0.16, type: "triangle" }, { freq: 1175, at: 0.12, length: 0.34, type: "triangle" }],
  stage: [{ freq: 523, at: 0, length: 0.16 }, { freq: 659, at: 0.13, length: 0.16 }, { freq: 784, at: 0.26, length: 0.3 }],
  cardKnown: [{ freq: 988, at: 0, length: 0.18, gain: 0.07 }],
};

export function soundEnabled(): boolean {
  try { return localStorage.getItem(STORAGE_KEY) !== "off"; } catch { return true; }
}

export function setSoundEnabled(enabled: boolean) {
  try { localStorage.setItem(STORAGE_KEY, enabled ? "on" : "off"); } catch { /* 無法保存時，本次仍依畫面上的開關運作。 */ }
}

let context: AudioContext | null = null;
let unlocked = false;

function audio(): AudioContext | null {
  if (context) return context;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  try { context = new Ctor(); } catch { return null; }
  return context;
}

export function playCue(cue: Cue) {
  if (!unlocked || !soundEnabled()) return;
  const ctx = audio();
  if (!ctx) return;
  if (ctx.state === "suspended") void ctx.resume().catch(() => undefined);
  const start = ctx.currentTime + 0.01;
  for (const note of cues[cue]) {
    const osc = ctx.createOscillator();
    const volume = ctx.createGain();
    const from = start + note.at;
    const peak = note.gain ?? 0.09;
    osc.type = note.type ?? "sine";
    osc.frequency.setValueAtTime(note.freq, from);
    if (note.to) osc.frequency.linearRampToValueAtTime(note.to, from + note.length);
    volume.gain.setValueAtTime(0.0001, from);
    volume.gain.exponentialRampToValueAtTime(peak, from + 0.015);
    volume.gain.exponentialRampToValueAtTime(0.0001, from + note.length);
    osc.connect(volume).connect(ctx.destination);
    osc.start(from);
    osc.stop(from + note.length + 0.02);
  }
}

// 解除靜音需要使用者操作；同時為主要按鈕加上輕微的點擊音。已有專屬提示音的按鈕標 data-silent-click。
export function installSound() {
  const unlock = () => { unlocked = true; };
  document.addEventListener("pointerdown", unlock, { capture: true, once: true });
  document.addEventListener("keydown", unlock, { capture: true, once: true });
  document.addEventListener("click", (event) => {
    unlocked = true;
    const button = event.target instanceof Element ? event.target.closest<HTMLElement>(".primary-button, .secondary-button") : null;
    if (button && !button.matches(":disabled, [aria-disabled='true']") && !button.closest("[data-silent-click]")) playCue("click");
  }, { capture: true });
}
