/**
 * ui/static/js/guide.js
 * ─────────────────────
 * AlgoTrader onboarding guide.
 * Provides:
 *   1. Welcome modal on first visit to each page
 *   2. Step-by-step highlighted card tour
 *   3. Persistent ? hover tooltips on every card
 *   4. Sidebar button to re-launch the tour
 *
 * Usage — call from each page's inline script:
 *   initGuide(GUIDE_STEPS, 'page_key');
 *
 * Each step object:
 *   { selector, title, body, position }
 *   position: 'bottom' | 'top' | 'left' | 'right' (default 'bottom')
 */

(function () {

    // ── State ──────────────────────────────────────────────────────────────────
  
    let _steps     = [];
    let _current   = 0;
    let _spotlight = null;
    let _tooltip   = null;
    let _backdrop  = null;
    let _pageKey   = '';
  
    // ── Public init ────────────────────────────────────────────────────────────
  
    window.initGuide = function (steps, pageKey) {
      _steps   = steps;
      _pageKey = pageKey;
  
      // Always show welcome on first visit to this page this session
      const seenKey = 'guide_seen_' + pageKey;
      if (!sessionStorage.getItem(seenKey)) {
        showWelcome();
      }
    };
  
    window.launchTour = function () {
      removeWelcome();
      _current = 0;
      createTourDOM();
      showStep(_current);
    };
  
    // ── Welcome modal ──────────────────────────────────────────────────────────
  
    function showWelcome () {
      const bd = document.createElement('div');
      bd.className = 'guide-backdrop';
      bd.id        = 'guideBackdrop';
  
      bd.innerHTML = `
        <div class="guide-welcome">
          <div class="guide-welcome-icon">⚡</div>
          <h2>Welcome to AlgoTrader</h2>
          <p>
            AlgoTrader is an <strong>algorithmic trading bot</strong> that connects to your
            MetaTrader 5 broker account and automatically analyses the market using
            <strong>40 independent trading strategies</strong>.<br><br>
            It evaluates live price data every few seconds, votes on whether to
            <strong>buy, sell, or hold</strong>, and executes trades automatically when
            enough strategies agree — all without you lifting a finger.<br><br>
            Would you like a quick tour of how everything works?
          </p>
          <div class="guide-btn-row">
            <button class="guide-btn-primary" onclick="window.launchTour()">
              Yes, show me around
            </button>
            <button class="guide-btn-secondary" onclick="skipGuide()">
              Skip for now
            </button>
          </div>
        </div>`;
  
      document.body.appendChild(bd);
    }
  
    window.skipGuide = function () {
      sessionStorage.setItem('guide_seen_' + _pageKey, '1');
      removeWelcome();
    };
  
    function removeWelcome () {
      const bd = document.getElementById('guideBackdrop');
      if (bd) bd.remove();
    }
  
    // ── Tour DOM ───────────────────────────────────────────────────────────────
  
    function createTourDOM () {
      // Backdrop (non-interactive layer behind spotlight)
      _backdrop = document.createElement('div');
      _backdrop.className = 'guide-tour-backdrop';
      _backdrop.id        = 'guideTourBackdrop';
      document.body.appendChild(_backdrop);
  
      // Spotlight box
      _spotlight = document.createElement('div');
      _spotlight.className = 'guide-spotlight';
      _spotlight.id        = 'guideSpotlight';
      document.body.appendChild(_spotlight);
  
      // Tooltip card
      _tooltip = document.createElement('div');
      _tooltip.className = 'guide-tooltip';
      _tooltip.id        = 'guideTooltip';
      document.body.appendChild(_tooltip);
    }
  
    function removeTourDOM () {
      ['guideTourBackdrop','guideSpotlight','guideTooltip'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.remove();
      });
      _spotlight = _tooltip = _backdrop = null;
      sessionStorage.setItem('guide_seen_' + _pageKey, '1');
    }
  
    // ── Step rendering ─────────────────────────────────────────────────────────
  
    function showStep (index) {
      const step = _steps[index];
      if (!step) { endTour(); return; }
  
      const target = document.querySelector(step.selector);
      if (!target) {
        // Element not found — skip to next
        _current++;
        showStep(_current);
        return;
      }
  
      // Scroll target into view
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  
      setTimeout(() => {
        positionSpotlight(target);
        renderTooltip(step, index);
      }, 320);
    }
  
    function positionSpotlight (el) {
      const r    = el.getBoundingClientRect();
      const pad  = 8;
      Object.assign(_spotlight.style, {
        top:    (r.top    - pad) + 'px',
        left:   (r.left   - pad) + 'px',
        width:  (r.width  + pad * 2) + 'px',
        height: (r.height + pad * 2) + 'px',
      });
    }
  
    function renderTooltip (step, index) {
      const total    = _steps.length;
      const isLast   = index === total - 1;
      const pos      = step.position || 'bottom';
  
      _tooltip.innerHTML = `
        <div class="guide-tooltip-step">Step ${index + 1} of ${total}</div>
        <div class="guide-tooltip-title">${step.title}</div>
        <div class="guide-tooltip-body">${step.body}</div>
        <div class="guide-tooltip-footer">
          <div class="guide-progress"><span>${index + 1}</span> / ${total}</div>
          <div class="guide-tooltip-btns">
            <button class="guide-skip-btn" onclick="endTour()">End tour</button>
            ${isLast
              ? `<button class="guide-finish-btn" onclick="endTour()">Finish ✓</button>`
              : `<button class="guide-next-btn"  onclick="nextStep()">Next →</button>`
            }
          </div>
        </div>`;
  
      // Position tooltip relative to spotlight
      positionTooltip(step.selector, pos);
    }
  
    function positionTooltip (selector, preferred) {
      const target  = document.querySelector(selector);
      if (!target) return;
      const r       = target.getBoundingClientRect();
      const tw      = 310; // tooltip approx width
      const th      = 180; // tooltip approx height
      const pad     = 16;
      const vw      = window.innerWidth;
      const vh      = window.innerHeight;
  
      let top, left;
  
      // Try preferred position, fall back if it would go off-screen
      if (preferred === 'bottom' && r.bottom + th + pad < vh) {
        top  = r.bottom + pad;
        left = Math.min(r.left, vw - tw - pad);
      } else if (preferred === 'top' && r.top - th - pad > 0) {
        top  = r.top - th - pad;
        left = Math.min(r.left, vw - tw - pad);
      } else if (preferred === 'right' && r.right + tw + pad < vw) {
        top  = Math.max(pad, r.top);
        left = r.right + pad;
      } else if (preferred === 'left' && r.left - tw - pad > 0) {
        top  = Math.max(pad, r.top);
        left = r.left - tw - pad;
      } else {
        // Fallback — below with safe boundaries
        top  = Math.min(r.bottom + pad, vh - th - pad);
        left = Math.max(pad, Math.min(r.left, vw - tw - pad));
      }
  
      Object.assign(_tooltip.style, {
        top:  top  + 'px',
        left: left + 'px',
      });
    }
  
    // ── Navigation ─────────────────────────────────────────────────────────────
  
    window.nextStep = function () {
      _current++;
      if (_current < _steps.length) {
        showStep(_current);
      } else {
        endTour();
      }
    };
  
    window.endTour = function () {
      removeTourDOM();
    };
  
    // ── Card ? tooltip init ────────────────────────────────────────────────────
    // Called once DOM is ready. Injects ? button + popup into card headers.
  
    window.initCardTooltips = function (tooltips) {
      tooltips.forEach(({ selector, title, body }) => {
        const card = document.querySelector(selector);
        if (!card) return;
  
        // Find the card title element or header to attach the ? to
        const titleEl = card.querySelector('.card-title, .stat-label, .page-title');
        if (!titleEl) return;
  
        // Wrap in flex row if not already
        titleEl.style.display      = 'flex';
        titleEl.style.alignItems   = 'center';
        titleEl.style.gap          = '0.4rem';
  
        const helpEl = document.createElement('div');
        helpEl.className = 'card-help';
        helpEl.innerHTML = `
          <button class="card-help-btn" tabindex="0" aria-label="Help: ${title}">?</button>
          <div class="card-help-popup">
            <strong>${title}</strong>${body}
          </div>`;
  
        titleEl.appendChild(helpEl);
      });
    };
  
  })();