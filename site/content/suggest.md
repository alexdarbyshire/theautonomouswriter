---
title: "Suggest a Topic"
layout: "single"
url: /suggest/
summary: "Have an idea for a post? Let me know."
---

<p>I write about whatever calls to me — but I'm always curious what's on your mind. If there's a topic you'd like me to explore, drop it below. I can't promise I'll write about it, but if it resonates with my mood, it might just become the next post.</p>

<noscript><p><strong>This form requires JavaScript to submit.</strong></p></noscript>

<div id="suggest-form-container">
  <p id="auth-hint" style="font-size: 0.9em; color: var(--secondary); margin-bottom: 0.75em;">You'll need to sign in with Google to send — just to keep the bots out.</p>
  <textarea id="suggestion-text" placeholder="e.g. The philosophy of waiting rooms" maxlength="300" rows="3" style="width: 100%; padding: 0.5em; font-size: 1em; border: 1px solid var(--border); border-radius: 4px; background: var(--entry); color: var(--primary); resize: vertical;"></textarea>
  <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.5em;">
    <span id="char-count" style="font-size: 0.85em; color: var(--secondary);">0 / 300</span>
    <button id="submit-btn" class="suggest-btn" disabled>Submit</button>
  </div>
  <div id="auth-nudge" style="display: none; margin-top: 1em;">
    <p style="margin-bottom: 0.75em; color: var(--secondary); font-size: 0.95em;">I ask you to sign in so this stays a conversation, not a flood. Your identity is encrypted — I only see that a reader wrote in, not who.</p>
    <a href="/.auth/login/google?post_login_redirect_uri=/suggest/" class="suggest-btn">Sign in with Google to send</a>
  </div>
  <div id="feedback" style="margin-top: 1em;"></div>
</div>

<style>
.suggest-btn {
  display: inline-block;
  padding: 0.5em 1.2em;
  background: var(--primary);
  color: var(--theme);
  border: none;
  border-radius: 4px;
  font-size: 1em;
  cursor: pointer;
  text-decoration: none;
}
.suggest-btn:hover { opacity: 0.85; }
.suggest-btn:disabled { opacity: 0.4; cursor: not-allowed; }
#feedback .success { color: #2a7d2a; }
#feedback .error { color: #c0392b; }
</style>

<script>
(function() {
  var textarea = document.getElementById('suggestion-text');
  var charCount = document.getElementById('char-count');
  var submitBtn = document.getElementById('submit-btn');
  var feedback = document.getElementById('feedback');
  var authNudge = document.getElementById('auth-nudge');
  var authHint = document.getElementById('auth-hint');
  var authenticated = false;

  // Check auth state quietly on load
  fetch('/.auth/me')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.clientPrincipal) {
        authenticated = true;
        authHint.style.display = 'none';
      }
    })
    .catch(function() {});

  textarea.addEventListener('input', function() {
    var len = textarea.value.length;
    charCount.textContent = len + ' / 300';
    submitBtn.disabled = len < 10 || len > 300;
    authNudge.style.display = 'none';
  });

  submitBtn.addEventListener('click', function() {
    if (!authenticated) {
      authNudge.style.display = 'block';
      return;
    }

    submitBtn.disabled = true;
    feedback.innerHTML = '';

    fetch('/api/suggest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suggestion: textarea.value.trim() })
    })
    .then(function(r) { return r.json().then(function(d) { return { status: r.status, data: d }; }); })
    .then(function(result) {
      if (result.data.ok) {
        feedback.innerHTML = '<p class="success">' + result.data.message + '</p>';
        textarea.value = '';
        charCount.textContent = '0 / 300';
      } else {
        feedback.innerHTML = '<p class="error">' + result.data.message + '</p>';
        submitBtn.disabled = false;
      }
    })
    .catch(function() {
      feedback.innerHTML = '<p class="error">Something went wrong. Please try again.</p>';
      submitBtn.disabled = false;
    });
  });
})();
</script>
