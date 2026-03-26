import { Board } from './Board.js';
import { SoundEngine } from './SoundEngine.js';
import { MessageRotator } from './MessageRotator.js';
import { KeyboardController } from './KeyboardController.js';
import { RemoteMessageSync } from './RemoteMessageSync.js';

document.addEventListener('DOMContentLoaded', () => {
  const boardContainer = document.getElementById('board-container');
  const soundEngine = new SoundEngine();
  const board = new Board(boardContainer, soundEngine);
  const rotator = new MessageRotator(board);
  const keyboard = new KeyboardController(rotator, soundEngine);
  const remoteSync = new RemoteMessageSync(handleRemoteState);
  let remoteOverrideActive = false;

  // Initialize audio on first user interaction (browser autoplay policy)
  let audioInitialized = false;
  const initAudio = async () => {
    if (audioInitialized) return;
    audioInitialized = true;
    await soundEngine.init();
    soundEngine.resume();
    document.removeEventListener('click', initAudio);
    document.removeEventListener('keydown', initAudio);
  };
  document.addEventListener('click', initAudio);
  document.addEventListener('keydown', initAudio);

  // Start message rotation
  rotator.start();

  // Volume toggle button in header
  const volumeBtn = document.getElementById('volume-btn');
  if (volumeBtn) {
    volumeBtn.addEventListener('click', () => {
      initAudio();
      const muted = soundEngine.toggleMute();
      volumeBtn.classList.toggle('muted', muted);
    });
  }

  // "Get Early Access" button: scroll to board and go fullscreen
  const ctaBtn = document.getElementById('cta-btn');
  if (ctaBtn) {
    ctaBtn.addEventListener('click', (e) => {
      e.preventDefault();
      initAudio();
      boardContainer.scrollIntoView({ behavior: 'smooth' });
      setTimeout(() => {
        document.documentElement.requestFullscreen().catch(() => {});
      }, 400);
    });
  }

  async function initializeMessages() {
    const initialState = await remoteSync.fetchInitialState();

    if (initialState && initialState.hasOverride) {
      handleRemoteState(initialState);
    } else {
      rotator.start();
    }

    remoteSync.connect();
  }

  function handleRemoteState(state) {
    if (!state || typeof state.hasOverride !== 'boolean') {
      return;
    }

    if (state.hasOverride) {
      remoteOverrideActive = true;
      rotator.enableRemoteOverride();
      board.displayMessage(Array.isArray(state.lines) ? state.lines : []);
      return;
    }

    if (remoteOverrideActive) {
      remoteOverrideActive = false;
      rotator.disableRemoteOverride({ showNextMessage: true });
      return;
    }

    if (!rotator.hasStarted()) {
      rotator.start();
    }
  }

  initializeMessages();
});
