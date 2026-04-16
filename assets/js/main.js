'use strict';

// Back to top
(function () {
  var bt = document.getElementById('back_to_top');
  if (!bt) return;

  window.addEventListener('scroll', function () {
    bt.style.display = window.scrollY > 30 ? 'block' : 'none';
  });

  bt.addEventListener('click', function (e) {
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
})();

// Nav toggle (mobile)
(function () {
  var icon = document.getElementById('menu_icon');
  var nav = document.getElementById('site_nav');
  if (!icon || !nav) return;

  icon.addEventListener('click', function () {
    nav.classList.toggle('nav-open');
  });
})();

// Lightbox
(function () {
  var overlay = null;
  var img = null;
  var currentThumb = null;

  var touchStartY = 0;
  var touchStartX = 0;
  var touchDeltaY = 0;
  var touchDeltaX = 0;
  var isSwiping = false;
  var tmRaf = 0;
  var cleanupGen = 0;

  function createOverlay() {
    overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';

    img = document.createElement('img');
    overlay.appendChild(img);

    document.body.appendChild(overlay);
    overlay.addEventListener('click', close);

    img.addEventListener('touchstart', onTouchStart, { passive: true });
    img.addEventListener('touchmove', onTouchMove, { passive: false });
    img.addEventListener('touchend', onTouchEnd);
    img.addEventListener('touchcancel', onTouchEnd);
  }

  function getThumbTransform(thumbEl) {
    var rect = thumbEl.getBoundingClientRect();
    // Read from thumbnail (already loaded on the page), not the lightbox img
    var natW = thumbEl.naturalWidth || rect.width;
    var natH = thumbEl.naturalHeight || rect.height;
    var maxW = window.innerWidth * 0.9;
    var maxH = window.innerHeight * 0.9;
    var ratio = Math.min(maxW / natW, maxH / natH, 1);
    var finalW = natW * ratio;
    var finalH = natH * ratio;

    var dx = (rect.left + rect.width / 2) - window.innerWidth / 2;
    var dy = (rect.top + rect.height / 2) - window.innerHeight / 2;
    var sx = rect.width / finalW;
    var sy = rect.height / finalH;

    return 'translate(' + dx + 'px,' + dy + 'px) scale(' + sx + ',' + sy + ')';
  }

  function isInViewport(el) {
    var r = el.getBoundingClientRect();
    return r.bottom > 0 && r.top < window.innerHeight
        && r.right > 0 && r.left < window.innerWidth;
  }

  function lockScroll() {
    var scrollbarW = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = 'hidden';
    if (scrollbarW > 0) {
      document.body.style.paddingRight = scrollbarW + 'px';
    }
  }

  function unlockScroll() {
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';
  }

  function open(thumbEl, src) {
    if (!overlay) createOverlay();
    cleanupGen++;
    currentThumb = thumbEl;
    img.src = src;

    img.style.transition = 'none';
    img.style.transform = getThumbTransform(thumbEl);
    img.style.opacity = '1';
    overlay.classList.add('lightbox-active');
    overlay.offsetHeight;

    img.style.transition = 'transform 0.35s cubic-bezier(0.2,0,0,1)';
    img.style.transform = 'none';
    lockScroll();
  }

  function resetOverlayStyles() {
    overlay.style.background = '';
    overlay.style.backdropFilter = '';
    overlay.style.webkitBackdropFilter = '';
  }

  function close() {
    if (!currentThumb) return;

    var useFlip = isInViewport(currentThumb);
    if (useFlip) {
      img.style.transition = 'transform 0.3s cubic-bezier(0.4,0,1,1)';
      img.style.transform = getThumbTransform(currentThumb);
    } else {
      img.style.transition = 'transform 0.25s, opacity 0.25s';
      img.style.opacity = '0';
    }
    overlay.classList.remove('lightbox-active');
    resetOverlayStyles();

    var myGen = ++cleanupGen;
    var cleanup = function () {
      if (myGen !== cleanupGen) return;
      img.style.transition = 'none';
      img.style.transform = '';
      img.style.opacity = '';
      unlockScroll();
      currentThumb = null;
    };

    if (useFlip) {
      img.addEventListener('transitionend', function handler(e) {
        if (e.propertyName !== 'transform') return;
        img.removeEventListener('transitionend', handler);
        cleanup();
      });
    } else {
      setTimeout(cleanup, 250);
    }
  }

  function onTouchStart(e) {
    if (e.touches.length !== 1) return;
    touchStartY = e.touches[0].clientY;
    touchStartX = e.touches[0].clientX;
    touchDeltaY = 0;
    touchDeltaX = 0;
    isSwiping = true;
    img.style.transition = 'none';
  }

  function onTouchMove(e) {
    if (!isSwiping || e.touches.length !== 1) return;
    touchDeltaY = e.touches[0].clientY - touchStartY;
    touchDeltaX = e.touches[0].clientX - touchStartX;

    if (Math.abs(touchDeltaY) < Math.abs(touchDeltaX)) return;
    if (e.cancelable) e.preventDefault();

    if (tmRaf) return;
    tmRaf = requestAnimationFrame(function () {
      tmRaf = 0;
      var progress = Math.min(Math.abs(touchDeltaY) / window.innerHeight, 1);
      var scale = 1 - progress * 0.3;
      img.style.transform = 'translate(' + (touchDeltaX * 0.3) + 'px,' + touchDeltaY + 'px) scale(' + scale + ')';
      var alpha = 0.7 * (1 - progress);
      var blur = 12 * (1 - progress);
      overlay.style.background = 'rgba(255,255,255,' + alpha + ')';
      overlay.style.backdropFilter = 'blur(' + blur + 'px)';
      overlay.style.webkitBackdropFilter = 'blur(' + blur + 'px)';
    });
  }

  function onTouchEnd() {
    if (!isSwiping) return;
    isSwiping = false;
    if (tmRaf) {
      cancelAnimationFrame(tmRaf);
      tmRaf = 0;
    }

    if (Math.abs(touchDeltaY) > 100) {
      close();
    } else {
      img.style.transition = 'transform 0.25s cubic-bezier(0.2,0,0,1)';
      img.style.transform = 'none';
      resetOverlayStyles();
    }
  }

  document.addEventListener('click', function (e) {
    var link = e.target.closest('[data-fancybox="gallery"]');
    if (link) {
      e.preventDefault();
      var thumbImg = link.querySelector('img') || e.target;
      open(thumbImg, link.href);
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (overlay && overlay.classList.contains('lightbox-active')) close();
  });
})();
