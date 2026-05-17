/* ============================================
   Sample Care Recruit — script.js
   ============================================ */

'use strict';

/* ------------------------------------------
   FAQ Accordion
   ------------------------------------------ */
(function initFAQ() {
  var faqItems = document.querySelectorAll('.faq-item');

  faqItems.forEach(function(item) {
    var question = item.querySelector('.faq-question');
    if (!question) return;

    question.addEventListener('click', function() {
      var isOpen = item.classList.contains('open');

      // Close all others
      faqItems.forEach(function(other) {
        if (other !== item) {
          other.classList.remove('open');
          var otherBtn = other.querySelector('.faq-question');
          if (otherBtn) otherBtn.setAttribute('aria-expanded', 'false');
        }
      });

      // Toggle current
      if (isOpen) {
        item.classList.remove('open');
        question.setAttribute('aria-expanded', 'false');
      } else {
        item.classList.add('open');
        question.setAttribute('aria-expanded', 'true');
      }
    });
  });
})();

/* ------------------------------------------
   Smooth Scroll
   ------------------------------------------ */
(function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
    anchor.addEventListener('click', function(e) {
      var targetId = this.getAttribute('href');
      if (targetId === '#') return;

      var target = document.querySelector(targetId);
      if (!target) return;

      e.preventDefault();

      var headerEl = document.querySelector('.site-header');
      var headerHeight = headerEl ? headerEl.offsetHeight : 0;
      var bannerEl = document.querySelector('.sample-banner');
      var bannerHeight = bannerEl ? bannerEl.offsetHeight : 0;
      var offset = headerHeight + bannerHeight + 12;

      var targetTop = target.getBoundingClientRect().top + window.pageYOffset - offset;

      window.scrollTo({
        top: targetTop,
        behavior: 'smooth'
      });
    });
  });
})();

/* ------------------------------------------
   Sticky Apply Button (mobile)
   ------------------------------------------ */
(function initStickyApply() {
  var stickyApply = document.getElementById('stickyApply');
  var hero = document.querySelector('.hero');
  var applySection = document.getElementById('apply');

  if (!stickyApply || !hero) return;

  function update() {
    if (window.innerWidth >= 768) return;

    var heroBottom = hero.getBoundingClientRect().bottom;
    var applyTop = applySection
      ? applySection.getBoundingClientRect().top
      : window.innerHeight + 1;

    if (heroBottom < 0 && applyTop > window.innerHeight * 0.5) {
      stickyApply.classList.add('visible');
    } else {
      stickyApply.classList.remove('visible');
    }
  }

  window.addEventListener('scroll', update, { passive: true });
  window.addEventListener('resize', update, { passive: true });
  update();
})();

/* ------------------------------------------
   Apply Form Validation & Submission
   ------------------------------------------ */
function handleApplySubmit(e) {
  e.preventDefault();

  var form = e.target;
  var isValid = true;

  // Clear previous errors
  document.querySelectorAll('.field-error').forEach(function(el) {
    el.textContent = '';
  });
  form.querySelectorAll('input, select, textarea').forEach(function(el) {
    el.style.borderColor = '';
  });

  // Name validation
  var nameEl = document.getElementById('apply-name');
  var name = nameEl ? nameEl.value.trim() : '';
  if (!name) {
    showError('err-name', 'お名前を入力してください。');
    if (nameEl) nameEl.style.borderColor = '#E53E3E';
    isValid = false;
  }

  // Phone validation
  var phoneEl = document.getElementById('apply-phone');
  var phone = phoneEl ? phoneEl.value.trim() : '';
  if (!phone) {
    showError('err-phone', '電話番号を入力してください。');
    if (phoneEl) phoneEl.style.borderColor = '#E53E3E';
    isValid = false;
  } else if (!/^[\d\-\+\(\) ]{7,15}$/.test(phone)) {
    showError('err-phone', '正しい電話番号を入力してください。');
    if (phoneEl) phoneEl.style.borderColor = '#E53E3E';
    isValid = false;
  }

  // Email validation
  var emailEl = document.getElementById('apply-email');
  var email = emailEl ? emailEl.value.trim() : '';
  if (!email) {
    showError('err-email', 'メールアドレスを入力してください。');
    if (emailEl) emailEl.style.borderColor = '#E53E3E';
    isValid = false;
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    showError('err-email', '正しいメールアドレスを入力してください。');
    if (emailEl) emailEl.style.borderColor = '#E53E3E';
    isValid = false;
  }

  // Intent (radio) validation
  var intentChecked = form.querySelector('input[name="intent"]:checked');
  if (!intentChecked) {
    showError('err-intent', 'ご希望の内容を選択してください。');
    isValid = false;
  }

  if (!isValid) {
    // Scroll to first error
    var firstError = form.querySelector('.field-error:not(:empty)');
    if (firstError) {
      var top = firstError.getBoundingClientRect().top + window.pageYOffset - 100;
      window.scrollTo({ top: top, behavior: 'smooth' });
    }
    return;
  }

  // Disable button and show loading
  var submitBtn = form.querySelector('[type="submit"]');
  submitBtn.textContent = '送信中...';
  submitBtn.disabled = true;

  // Formspree 実送信
  // ※ FORMSPREE_ENDPOINT_SAMPLE を自分のエンドポイントに差し替える
  //    例: 'https://formspree.io/f/yyyyyyyy'
  var FORMSPREE_ENDPOINT_SAMPLE = 'https://formspree.io/f/YYYYYYYY'; // ← ここを変える

  var data = new FormData(form);

  fetch(FORMSPREE_ENDPOINT_SAMPLE, {
    method: 'POST',
    body: data,
    headers: { 'Accept': 'application/json' }
  })
  .then(function(res) {
    if (res.ok) {
      form.style.display = 'none';
      var successEl = document.getElementById('applySuccess');
      if (successEl) {
        successEl.style.display = 'block';
        var top = successEl.getBoundingClientRect().top + window.pageYOffset - 100;
        window.scrollTo({ top: top, behavior: 'smooth' });
      }
      var sticky = document.getElementById('stickyApply');
      if (sticky) sticky.classList.remove('visible');
    } else {
      return res.json().then(function(data) { throw data; });
    }
  })
  .catch(function() {
    submitBtn.textContent = '送信する';
    submitBtn.disabled = false;
    alert('送信に失敗しました。お手数ですが、お電話にてご連絡ください。');
  });
}

function showError(id, message) {
  var el = document.getElementById(id);
  if (el) el.textContent = message;
}
