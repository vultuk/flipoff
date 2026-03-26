import { MESSAGES, MESSAGE_INTERVAL, TOTAL_TRANSITION } from './constants.js';

export class MessageRotator {
  constructor(board) {
    this.board = board;
    this.messages = MESSAGES;
    this.currentIndex = -1;
    this._timer = null;
    this._paused = false;
    this._remoteOverride = false;
  }

  start({ immediate = true } = {}) {
    if (immediate) {
      this.next();
    }

    this._paused = false;
    this._ensureTimer();
  }

  stop() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  next() {
    if (this._remoteOverride || this.messages.length === 0) return;

    this.currentIndex = (this.currentIndex + 1) % this.messages.length;
    this.board.displayMessage(this.messages[this.currentIndex]);
    this._resetAutoRotation();
  }

  prev() {
    if (this._remoteOverride || this.messages.length === 0) return;

    this.currentIndex = (this.currentIndex - 1 + this.messages.length) % this.messages.length;
    this.board.displayMessage(this.messages[this.currentIndex]);
    this._resetAutoRotation();
  }

  hasStarted() {
    return this._timer !== null || this.currentIndex !== -1;
  }

  enableRemoteOverride() {
    this._remoteOverride = true;
    this._paused = true;
  }

  disableRemoteOverride({ showNextMessage = true } = {}) {
    this._remoteOverride = false;
    this._paused = false;
    this._ensureTimer();

    if (showNextMessage) {
      this.next();
      return;
    }

    this._resetAutoRotation();
  }

  _ensureTimer() {
    if (this._timer) return;

    this._timer = setInterval(() => {
      if (!this._paused && !this.board.isTransitioning) {
        this.next();
      }
    }, MESSAGE_INTERVAL + TOTAL_TRANSITION);
  }

  _resetAutoRotation() {
    // Reset timer when user manually navigates
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
      this._ensureTimer();
    }
  }
}
