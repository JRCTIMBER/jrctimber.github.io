{
  // Mobile menu
  const btn = document.querySelector(".menu"), nav = document.getElementById("nav");
  if (btn && nav) {
    const set = open => { btn.setAttribute("aria-expanded", open); nav.classList.toggle("open", open); };
    btn.addEventListener("click", () => set(btn.getAttribute("aria-expanded") !== "true"));
    nav.addEventListener("click", e => { if (e.target.closest("a")) set(false); });
    document.addEventListener("keydown", e => { if (e.key === "Escape") set(false); });
  }
  // Header shadow once the page scrolls
  const top = document.querySelector(".top");
  const onScroll = () => top && top.classList.toggle("scrolled", window.scrollY > 8);
  addEventListener("scroll", onScroll, {passive: true}); onScroll();

  // Ease sections in as they scroll into view. Anything already on screen is left alone,
  // so nothing is ever hidden at load.
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!calm && "IntersectionObserver" in window) {
    const io = new IntersectionObserver(entries => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }, {rootMargin: "0px 0px -8% 0px"});
    const groups = [".rev-top", ".faq-head", ".qs", ".intro", ".svcs > li", ".gal > button", ".about-pic", ".about .txt", ".reach", ".panel", ".info > div", ".tools"];
    for (const sel of groups) {
      document.querySelectorAll(sel).forEach((el, i) => {
        if (el.getBoundingClientRect().top < innerHeight) return;
        el.style.setProperty("--d", (i % 4) * 0.08 + "s");
        el.classList.add("reveal"); io.observe(el);
      });
    }
  }

  const yr = document.getElementById("yr");
  if (yr) yr.textContent = new Date().getFullYear();
}
