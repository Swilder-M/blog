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

  function createOverlay() {
    overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';
    img = document.createElement('img');
    overlay.appendChild(img);
    document.body.appendChild(overlay);
    overlay.addEventListener('click', close);
  }

  // Calculate transform to position centered image at thumbnail location
  function getThumbTransform(thumbEl) {
    var rect = thumbEl.getBoundingClientRect();
    var natW = img.naturalWidth || rect.width;
    var natH = img.naturalHeight || rect.height;
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

  function open(src, thumbEl) {
    if (!overlay) createOverlay();
    currentThumb = thumbEl;
    img.src = src;

    // Start at thumbnail position
    img.style.transition = 'none';
    img.style.transform = getThumbTransform(thumbEl);
    img.style.opacity = '1';
    overlay.classList.add('lightbox-active');
    overlay.offsetHeight;

    // Animate to center
    img.style.transition = 'transform 0.35s cubic-bezier(0.2,0,0,1)';
    img.style.transform = 'none';
    document.body.style.overflow = 'hidden';
  }

  function close() {
    if (!currentThumb) return;

    // Animate back to thumbnail position
    img.style.transition = 'transform 0.3s cubic-bezier(0.4,0,1,1)';
    img.style.transform = getThumbTransform(currentThumb);
    overlay.classList.remove('lightbox-active');

    img.addEventListener('transitionend', function handler(e) {
      if (e.propertyName !== 'transform') return;
      img.removeEventListener('transitionend', handler);
      img.style.transition = 'none';
      img.style.transform = '';
      img.style.opacity = '';
      document.body.style.overflow = '';
      currentThumb = null;
    });
  }

  document.addEventListener('click', function (e) {
    var link = e.target.closest('[data-fancybox="gallery"]');
    if (link) {
      e.preventDefault();
      var thumbImg = link.querySelector('img') || e.target;
      open(link.href, thumbImg);
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && overlay && overlay.classList.contains('lightbox-active')) {
      close();
    }
  });
})();
