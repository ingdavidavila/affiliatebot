// Hover tooltip + crosshair for the daily chart.
document.querySelectorAll(".chart-wrap").forEach((wrap) => {
  const svg = wrap.querySelector("svg");
  const tip = wrap.querySelector(".tip");
  const cross = svg.querySelector(".crosshair");
  const series = wrap.dataset.series.split("|").map((s) => s.split(":"));
  const colors = ["--series-1", "--series-2"];
  const money = (v) => "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  svg.querySelectorAll(".hit").forEach((hit) => {
    hit.addEventListener("mouseenter", () => {
      const x = hit.dataset.x;
      cross.setAttribute("x1", x);
      cross.setAttribute("x2", x);
      cross.setAttribute("visibility", "visible");
      const d = new Date(hit.dataset.date + "T12:00:00");
      let html = `<div class="d">${d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</div>`;
      let net = 0;
      series.forEach(([key, label], i) => {
        const v = parseFloat(hit.dataset[key]);
        net += i === 0 ? v : -v;
        html += `<div class="r"><span><i style="background:var(${colors[i]})"></i>${label}</span><span>${money(v)}</span></div>`;
      });
      html += `<div class="r"><span>Net</span><span>${net < 0 ? "−" : ""}${money(Math.abs(net))}</span></div>`;
      tip.innerHTML = html;
      tip.hidden = false;
      const box = svg.getBoundingClientRect();
      const wrapBox = wrap.getBoundingClientRect();
      const px = (x / svg.viewBox.baseVal.width) * box.width + (box.left - wrapBox.left);
      const left = px + 12 + 170 > wrapBox.width ? px - 12 - tip.offsetWidth : px + 12;
      tip.style.left = left + "px";
      tip.style.top = box.top - wrapBox.top + 24 + "px";
    });
  });
  svg.addEventListener("mouseleave", () => {
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
  });
});
