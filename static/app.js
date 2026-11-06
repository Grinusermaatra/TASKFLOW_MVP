(function () {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const csrf = meta ? meta.content : "";

  function toast(message, kind) {
    if (!message) return;
    const host = document.getElementById("toasts");
    if (!host) return;
    const el = document.createElement("div");
    el.setAttribute("role", "status");
    el.className = "pointer-events-auto w-full max-w-sm rounded-2xl px-4 py-3 text-sm font-medium shadow-lg " +
      (kind === "error" ? "bg-red-600 text-white" : "bg-slate-900 text-white");
    el.textContent = message;
    host.appendChild(el);
    setTimeout(function () { el.remove(); }, 3800);
  }

  if (window.__FLASH__) toast(window.__FLASH__, "ok");

  document.querySelectorAll("[data-absolute-url]").forEach(function (el) {
    const path = el.getAttribute("data-absolute-url") || "";
    if (path.startsWith("/")) el.textContent = window.location.origin + path;
  });

  function errorMessage(data) {
    if (!data) return "Ocurrió un error";
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map(function (item) { return item.msg || ""; }).filter(Boolean).join(" ") || "Datos inválidos";
    }
    return "Ocurrió un error";
  }

  function showSecret(data) {
    const box = document.getElementById("secret-box");
    if (!box) return;
    box.classList.remove("hidden");
    box.replaceChildren();
    const title = document.createElement("p");
    title.className = "font-semibold text-slate-900";
    if (data.temporary_password) {
      title.textContent = "Colaborador creado";
      const note = document.createElement("p");
      note.className = "mt-2 text-sm text-slate-700";
      note.textContent = "Comparte estas credenciales. La contraseña solo se muestra ahora.";
      const cred = document.createElement("pre");
      cred.className = "mt-3 whitespace-pre-wrap rounded-2xl bg-slate-900 p-3 text-sm text-white";
      cred.textContent = "Usuario: " + data.username + "\nContraseña: " + data.temporary_password;
      box.append(title, note, cred);
      return;
    }
    if (data.invite_url) {
      title.textContent = "Enlace de invitación";
      const link = document.createElement("p");
      link.className = "mt-2 break-all text-sm text-indigo-700";
      const path = data.invite_url;
      link.textContent = path.startsWith("http") ? path : window.location.origin + path;
      const note = document.createElement("p");
      note.className = "mt-2 text-sm text-slate-600";
      note.textContent = "Vence en 7 días y registra un colaborador de tu organización.";
      box.append(title, link, note);
    }
  }

  document.querySelectorAll("form[data-enhance]").forEach(function (form) {
    form.addEventListener("submit", async function (event) {
      if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      const button = form.querySelector("button[type=submit]");
      const original = button ? button.textContent : "";
      if (button) {
        button.disabled = true;
        button.textContent = "Guardando…";
      }
      const kind = form.dataset.kind || "empty";
      const method = (form.dataset.method || "POST").toUpperCase();
      const url = form.dataset.api || form.action;
      try {
        if (kind === "multipart") {
          const input = form.querySelector('input[type="file"]');
          if (!input || !input.files || !input.files.length) {
            toast("La foto es obligatoria", "error");
            return;
          }
        }
        const headers = {
          Accept: "application/json",
          "X-CSRF-Token": csrf,
          "X-Requested-With": "fetch",
        };
        let body;
        if (kind === "json") {
          const payload = {};
          new FormData(form).forEach(function (value, key) {
            if (key === "csrf_token" || typeof value !== "string") return;
            if (key === "password" && value === "") return;
            if ((key === "due_date" || key === "comment") && value === "") {
              payload[key] = null;
              return;
            }
            payload[key] = key === "assigned_to" ? Number(value) : value;
          });
          headers["Content-Type"] = "application/json";
          body = JSON.stringify(payload);
        } else if (kind === "multipart") {
          body = new FormData(form);
        }
        const response = await fetch(url, { method: method, headers: headers, body: body });
        const text = await response.text();
        let data = {};
        if (text) {
          try { data = JSON.parse(text); } catch (_err) { data = { detail: text }; }
        }
        if (response.status === 401) {
          window.location.href = "/login";
          return;
        }
        if (!response.ok) {
          toast(errorMessage(data), "error");
          return;
        }
        if (data.temporary_password || data.invite_url) {
          showSecret(data);
          toast(data.message || "Listo", "ok");
          return;
        }
        toast(data.message || "Listo", "ok");
        const dest = data.redirect || form.dataset.redirect;
        if (dest) {
          window.setTimeout(function () { window.location.href = dest; }, 450);
        }
      } catch (_err) {
        toast("No se pudo contactar al servidor", "error");
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = original;
        }
      }
    });
  });

  const photo = document.getElementById("photo-input");
  const preview = document.getElementById("photo-preview");
  if (photo && preview) {
    photo.addEventListener("change", function () {
      const file = photo.files && photo.files[0];
      const name = document.getElementById("photo-name");
      if (!file) {
        preview.classList.add("hidden");
        preview.removeAttribute("src");
        if (name) name.textContent = "";
        return;
      }
      if (name) name.textContent = file.name;
      preview.src = URL.createObjectURL(file);
      preview.classList.remove("hidden");
    });
  }
})();
