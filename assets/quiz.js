// Shared quiz state across the progressive-disclosure pages.
const Quiz = (() => {
  const KEY = "curlcollection.quiz";
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
  const save = (state) => localStorage.setItem(KEY, JSON.stringify(state));
  // Read query params into state on load (e.g. ?hair_type=3A).
  const init = (fields) => {
    const s = load();
    const p = new URLSearchParams(location.search);
    for (const f of fields) if (p.has(f)) s[f] = p.get(f);
    save(s);
    return s;
  };
  const set = (patch) => { const s = { ...load(), ...patch }; save(s); return s; };
  const get = () => load();
  const reset = () => localStorage.removeItem(KEY);
  return { init, set, get, reset, KEY };
})();
