/* ============================================
   Service LP — script.js
   ============================================ */

'use strict';

/* ------------------------------------------
   FAQ Accordion
   ------------------------------------------ */
(function initFAQ() {
  const faqItems = document.querySelectorAll('.faq-item');

  faqItems.forEach(function(item) {
    const question = item.querySelector('.faq-question');
    if (!question) return;

    question.addEventListener('click', function() {
      const isOpen = item.classList.contains('open');

      // Close all others
      faqItems.forEach(function(other) {
        if (other !== item) {
          other.classList.remove('open');
          const otherBtn = other.querySelector('.faq-question');
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
   Smooth Scroll for anchor links
   ------------------------------------------ */
(function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
    anchor.addEventListener('click', function(e) {
      const targetId = this.getAttribute('href');
      if (targetId === '#') return;

      const target = document.querySelector(targetId);
      if (!target) return;

      e.preventDefault();

      const headerHeight = document.querySelector('.site-header')
        ? document.querySelector('.site-header').offsetHeight
        : 0;

      const targetTop = target.getBoundingClientRect().top + window.pageYOffset - headerHeight - 16;

      window.scrollTo({
        top: targetTop,
        behavior: 'smooth'
      });
    });
  });
})();

/* ------------------------------------------
   Sticky CTA Button (mobile)
   ------------------------------------------ */
(function initStickyCta() {
  const stickyCta = document.getElementById('stickyCta');
  const hero = document.querySelector('.hero');
  const finalCta = document.querySelector('.section-final-cta');

  if (!stickyCta || !hero) return;

  function updateStickyCta() {
    // Only show on mobile (handled by CSS for desktop)
    if (window.innerWidth >= 768) return;

    const heroBottom = hero.getBoundingClientRect().bottom;
    const finalCtaTop = finalCta
      ? finalCta.getBoundingClientRect().top
      : window.innerHeight + 1;

    // Show after scrolling past hero, hide when final CTA is in view
    if (heroBottom < 0 && finalCtaTop > window.innerHeight) {
      stickyCta.classList.add('visible');
    } else {
      stickyCta.classList.remove('visible');
    }
  }

  window.addEventListener('scroll', updateStickyCta, { passive: true });
  window.addEventListener('resize', updateStickyCta, { passive: true });
  updateStickyCta();
})();

/* ------------------------------------------
   Form submission handler
   Formspree を使った実送信対応
   ※ FORMSPREE_ENDPOINT を自分のエンドポイントに差し替える
      例: 'https://formspree.io/f/xxxxxxxx'
      取得方法: https://formspree.io/ でフォーム作成後に発行される
   ------------------------------------------ */
var FORMSPREE_ENDPOINT = 'https://formspree.io/f/xaqkwzew'; // 送信先: oka.ponomedia@gmail.com

function handleFormSubmit(e) {
  e.preventDefault();

  var form = e.target;
  var facilityName = form.querySelector('#facility-name').value.trim();
  var contactName = form.querySelector('#contact-name').value.trim();
  var contactEmail = form.querySelector('#contact-email').value.trim();
  var submitBtn = form.querySelector('[type="submit"]');

  // Validation
  if (!facilityName || !contactName || !contactEmail) {
    alert('施設名・担当者名・メールアドレスは必須項目です。');
    return;
  }
  var emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailPattern.test(contactEmail)) {
    alert('正しいメールアドレスを入力してください。');
    return;
  }

  // 送信中表示
  submitBtn.textContent = '送信中...';
  submitBtn.disabled = true;

  var data = new FormData(form);

  fetch(FORMSPREE_ENDPOINT, {
    method: 'POST',
    body: data,
    headers: { 'Accept': 'application/json' }
  })
  .then(function(res) {
    if (res.ok) {
      // 成功
      form.style.display = 'none';
      var thanks = document.createElement('div');
      thanks.style.cssText = 'padding:40px 20px;text-align:center;background:#E8F8F0;border-radius:16px;';
      thanks.innerHTML = '<div style="font-size:2.5rem;margin-bottom:12px;">✓</div>'
        + '<p style="font-weight:700;font-size:1.1rem;color:#27AE60;margin-bottom:8px;">送信が完了しました</p>'
        + '<p style="color:#555;font-size:0.95rem;line-height:1.8;">お問い合わせありがとうございます。<br>担当者より2営業日以内にご連絡いたします。</p>';
      form.parentNode.appendChild(thanks);
    } else {
      return res.json().then(function(data) { throw data; });
    }
  })
  .catch(function() {
    submitBtn.textContent = '無料診断を依頼する';
    submitBtn.disabled = false;
    alert('送信に失敗しました。お手数ですが、時間をおいて再度お試しください。');
  });
}
