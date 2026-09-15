"""Rend la spécification v1.0 en page de relecture, modifications surlignées.

Appelé par build.sh, qui lui fournit le diff et la liste des commits : ce module
ne lance aucune commande git lui-même.
"""

from __future__ import annotations

import argparse
import json
import re

FIELD_ORDER = ("Motif", "Vérification", "Source")


def parse_touched(diff: str) -> set[int]:
    """Numéros de ligne du fichier courant touchés par le diff."""
    touched: set[int] = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start = int(m.group(1))
        length = int(m.group(2) or 1)
        touched.update(range(start, start + length) if length else [start])
    return touched


def classify(spec: str, touched: set[int]) -> dict:
    lines = spec.split("\n")
    heads = [
        (i, re.sub(r"^#+ ", "", line).strip())
        for i, line in enumerate(lines, 1)
        if re.match(r"^#{2,3} ", line)
    ]
    bounds = []
    for idx, (start, title) in enumerate(heads):
        end = heads[idx + 1][0] - 1 if idx + 1 < len(heads) else len(lines)
        bounds.append((start, end, title))

    def meaningful(n: int) -> bool:
        # Une ligne vide ou un séparateur ne rend pas une section modifiée :
        # l'insertion d'un chapitre entier commence par « --- », qui tombe dans
        # la portée de la section précédente.
        return 1 <= n <= len(lines) and lines[n - 1].strip() not in ("", "---")

    changed, renumbered = [], []
    for start, end, title in bounds:
        hit = {n for n in touched if start <= n <= end and meaningful(n)}
        if not hit:
            continue
        # Seule la ligne de titre a bougé : c'est une renumérotation, pas une
        # modification de fond. Les distinguer évite de relire pour rien.
        (renumbered if hit == {start} else changed).append(title)

    reqs = []
    for i, line in enumerate(lines, 1):
        m = re.match(r"^(EXG-[A-Z]{3}-\d{3})", line)
        if not m:
            continue
        end = i
        while end < len(lines) and not lines[end].startswith("```"):
            end += 1
        reqs.append((i, end, m.group(1)))
    changed_reqs = sorted({c for s, e, c in reqs if any(s <= n <= e for n in touched)})

    return {
        "changed": changed,
        "renumbered": renumbered,
        "changedRequirements": changed_reqs,
        "totalRequirements": len(reqs),
        "chaptersWritten": len(
            [1 for line in lines if line.startswith("**Statut : ") and "rédig" not in line]
        ),
        "chaptersPlanned": 18,
        "openQuestions": len([1 for line in lines if re.match(r"^\d+\. \*\*", line)]),
    }


TEMPLATE = r"""<title>Spécification Waterfall v1.0</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,300;0,400;0,500;0,600;1,400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --ground:#f3f5f8; --surface:#ffffff; --surface-2:#eef2f6;
  --ink:#15202c; --ink-2:#2c3c4d; --muted:#59697b; --faint:#8595a6;
  --rule:#dce3ea; --rule-strong:#c3cedb;
  --accent:#1d4e79; --accent-soft:#e7eff7; --accent-ink:#1d4e79;
  --flag:#6d3fa3; --flag-soft:#f2ecfa; --flag-rule:#c9b1e8;
  --ok:#2c6a4c; --partial:#8a5f14; --open:#a03a2e;
  --serif:"Spectral",Georgia,"Times New Roman",serif;
  --sans:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,monospace;
  --rail:270px;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0e131a; --surface:#151d26; --surface-2:#1b242f;
    --ink:#dde5ed; --ink-2:#c2cdd9; --muted:#8b9aab; --faint:#6c7c8d;
    --rule:#26313d; --rule-strong:#35434f;
    --accent:#7ab3e5; --accent-soft:#152534; --accent-ink:#9cc8f0;
    --flag:#bd9aec; --flag-soft:#211a31; --flag-rule:#4b3a6b;
    --ok:#6dbf94; --partial:#d5a244; --open:#e08578;
  }
}
:root[data-theme="dark"]{
  --ground:#0e131a; --surface:#151d26; --surface-2:#1b242f;
  --ink:#dde5ed; --ink-2:#c2cdd9; --muted:#8b9aab; --faint:#6c7c8d;
  --rule:#26313d; --rule-strong:#35434f;
  --accent:#7ab3e5; --accent-soft:#152534; --accent-ink:#9cc8f0;
  --flag:#bd9aec; --flag-soft:#211a31; --flag-rule:#4b3a6b;
  --ok:#6dbf94; --partial:#d5a244; --open:#e08578;
}

*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font-family:var(--serif);
  font-size:16.5px;line-height:1.72;-webkit-font-smoothing:antialiased}
a{color:var(--accent-ink)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
html{scroll-behavior:smooth}

.shell{display:grid;grid-template-columns:var(--rail) minmax(0,1fr);
  max-width:1320px;margin:0 auto;align-items:start}

.rail{position:sticky;top:0;height:100vh;overflow-y:auto;padding:26px 18px 40px 24px;
  border-right:1px solid var(--rule);font-family:var(--sans);font-size:12.5px;line-height:1.45}
.rail-id{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--faint);margin-bottom:14px}
.nav{display:flex;flex-direction:column;gap:1px;margin-bottom:22px}
.nav a{display:flex;align-items:baseline;gap:7px;padding:3.5px 8px;border-radius:4px;
  color:var(--muted);text-decoration:none;border-left:2px solid transparent}
.nav a:hover{background:var(--surface-2);color:var(--ink)}
.nav a.lvl3{padding-left:20px;font-size:12px}
.nav a.on{background:var(--accent-soft);color:var(--accent-ink);
  border-left-color:var(--accent);font-weight:500}
.nav a .num{font-family:var(--mono);font-size:10.5px;color:var(--faint);min-width:22px}
.nav a.on .num{color:var(--accent-ink)}
.nav .dot{width:5px;height:5px;border-radius:50%;background:var(--flag);
  flex:0 0 auto;align-self:center;margin-left:auto}
.rail-note{font-size:11.5px;color:var(--faint);border-top:1px solid var(--rule);
  padding-top:12px;line-height:1.5}

.main{padding:0 0 120px}
.masthead{padding:44px 34px 22px;border-bottom:1px solid var(--rule)}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted)}
.masthead h1{font-weight:600;font-size:clamp(30px,4vw,42px);line-height:1.12;
  margin:10px 0 0;letter-spacing:-.015em;text-wrap:balance}
.deck{color:var(--muted);font-size:17px;margin:12px 0 0;max-width:62ch}

.stats{display:flex;flex-wrap:wrap;margin:22px 0 0;font-family:var(--sans);
  border:1px solid var(--rule);border-radius:6px;overflow:hidden;background:var(--surface);
  max-width:fit-content}
.stat{padding:9px 18px;border-right:1px solid var(--rule)}
.stat:last-child{border-right:0}
.stat b{display:block;font-family:var(--mono);font-size:19px;font-weight:500;
  color:var(--ink);font-variant-numeric:tabular-nums;line-height:1.2}
.stat span{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--faint)}

.controls{position:sticky;top:0;z-index:20;background:var(--ground);
  border-bottom:1px solid var(--rule);padding:11px 34px;
  display:flex;flex-wrap:wrap;align-items:center;gap:14px;font-family:var(--sans);font-size:12.5px}
.base{color:var(--muted)}
.base code{font-family:var(--mono);font-size:11.5px;background:var(--surface-2);
  padding:1.5px 6px;border-radius:3px;color:var(--ink-2)}
.toggle{display:inline-flex;align-items:center;gap:7px;cursor:pointer;color:var(--muted);
  user-select:none}
.toggle input{accent-color:var(--flag);width:14px;height:14px;margin:0;cursor:pointer}
.toggle:hover{color:var(--ink)}

.changelog{margin:26px 34px 0;max-width:70ch;border:1px solid var(--flag-rule);
  border-radius:7px;background:var(--flag-soft);padding:18px 20px;font-family:var(--sans)}
.changelog h2{font-family:var(--sans);font-size:12px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--flag);margin:0 0 12px;font-weight:600}
.changelog ol{margin:0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:7px}
.changelog li{display:flex;gap:10px;font-size:13.5px;line-height:1.5;color:var(--ink-2)}
.changelog li code{font-family:var(--mono);font-size:11.5px;color:var(--flag);flex:0 0 auto}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:14px;padding-top:13px;
  border-top:1px solid var(--flag-rule)}
.chips b{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
  font-weight:500;align-self:center;margin-right:4px}
.chip{font-family:var(--mono);font-size:11px;padding:2.5px 7px;border-radius:3px;
  background:var(--surface);border:1px solid var(--flag-rule);color:var(--flag);
  text-decoration:none}
.chip:hover{background:var(--flag);color:var(--surface)}

section{padding:30px 34px 4px;border-left:3px solid transparent;scroll-margin-top:56px}
section.changed{border-left-color:var(--flag);
  background:linear-gradient(to right,var(--flag-soft),transparent 340px)}
body.plain section.changed{border-left-color:transparent;background:none}
section > *{max-width:70ch}
section.intro{padding-top:26px;color:var(--muted);font-size:15.5px}
section.intro strong{color:var(--ink)}
section h2,section h3{letter-spacing:-.01em;text-wrap:balance}
section h2{font-size:26px;font-weight:600;margin:6px 0 14px;line-height:1.2}
section h3{font-size:19px;font-weight:600;margin:4px 0 12px;color:var(--ink)}
.tag{font-family:var(--sans);font-size:10px;font-weight:600;letter-spacing:.08em;
  text-transform:uppercase;padding:2px 7px;border-radius:3px;vertical-align:middle;
  margin-left:9px;white-space:nowrap}
.tag.mod{background:var(--flag);color:#fff}
.tag.renum{background:var(--surface-2);color:var(--muted);border:1px solid var(--rule)}
body.plain .tag{display:none}

p{margin:0 0 14px}
strong{font-weight:600;color:var(--ink)}
ul,ol{margin:0 0 15px;padding-left:22px}
li{margin-bottom:5px}
hr{border:0;border-top:1px solid var(--rule);margin:34px 0}
code{font-family:var(--mono);font-size:.855em;background:var(--surface-2);
  padding:1px 5px;border-radius:3px;color:var(--ink-2)}
blockquote{border-left:2px solid var(--rule-strong);margin:0 0 15px;padding-left:16px;
  color:var(--muted);font-style:italic}

.tablewrap{overflow-x:auto;margin:0 0 20px;border:1px solid var(--rule);border-radius:6px;
  background:var(--surface);max-width:70ch}
table{border-collapse:collapse;width:100%;font-family:var(--sans);font-size:13px;line-height:1.5}
th,td{text-align:left;padding:9px 13px;border-bottom:1px solid var(--rule);vertical-align:top}
th{background:var(--surface-2);font-weight:600;font-size:11px;letter-spacing:.06em;
  text-transform:uppercase;color:var(--muted);white-space:nowrap}
tr:last-child td{border-bottom:0}
td code{font-size:11.5px}

pre{overflow-x:auto;background:var(--surface);border:1px solid var(--rule);border-radius:6px;
  padding:16px 18px;margin:0 0 20px;font-family:var(--mono);font-size:12.5px;line-height:1.65;
  color:var(--ink-2);max-width:70ch}
pre code{background:none;padding:0;font-size:inherit}

.req{border:1px solid var(--rule);border-left:3px solid var(--accent);border-radius:6px;
  background:var(--surface);margin:0 0 20px;overflow:hidden;max-width:70ch;scroll-margin-top:64px}
.req.touched{border-left-color:var(--flag)}
body.plain .req.touched{border-left-color:var(--accent)}
.req.dropped{border-left-color:var(--rule-strong);background:var(--surface-2)}
.req-head{display:flex;flex-wrap:wrap;align-items:center;gap:9px;padding:11px 16px 0}
.req-code{font-family:var(--mono);font-size:12.5px;font-weight:500;color:var(--accent-ink)}
.req.dropped .req-code{color:var(--muted);text-decoration:line-through}
.lvl{font-family:var(--sans);font-size:10px;font-weight:600;letter-spacing:.09em;
  text-transform:uppercase;padding:2.5px 7px;border-radius:3px;background:var(--accent);color:#fff}
.lvl.devrait{background:var(--partial)}
.lvl.peut{background:var(--surface-2);color:var(--muted);border:1px solid var(--rule)}
.lvl.abandonnee{background:var(--surface-2);color:var(--muted);border:1px solid var(--rule-strong)}
.req-flag{margin-left:auto;font-family:var(--sans);font-size:10px;font-weight:600;
  letter-spacing:.08em;text-transform:uppercase;color:var(--flag)}
body.plain .req-flag{display:none}
.req-statement{padding:8px 16px 12px;font-size:16px;line-height:1.6}
.req-fields{display:grid;grid-template-columns:auto minmax(0,1fr);
  border-top:1px solid var(--rule);font-size:14px}
.req-fields dt{font-family:var(--sans);font-size:10.5px;font-weight:600;letter-spacing:.07em;
  text-transform:uppercase;color:var(--muted);padding:9px 14px 9px 16px;white-space:nowrap;
  border-bottom:1px solid var(--rule);background:var(--surface-2)}
.req-fields dd{margin:0;padding:9px 16px;color:var(--ink-2);line-height:1.55;
  border-bottom:1px solid var(--rule)}
.req-fields dt:last-of-type,.req-fields dd:last-of-type{border-bottom:0}

body.only section:not(.changed){display:none}
body.only .nav a:not(.has-dot){display:none}
.empty{display:none;padding:40px 34px;color:var(--muted);font-style:italic}

@media(max-width:900px){
  .shell{grid-template-columns:1fr}
  .rail{position:static;height:auto;border-right:0;border-bottom:1px solid var(--rule)}
  .nav{max-height:230px;overflow-y:auto}
  section,.masthead,.controls{padding-left:20px;padding-right:20px}
  .changelog{margin-left:20px;margin-right:20px}
}
</style>

<div class="shell">
  <aside class="rail">
    <div class="rail-id">Waterfall · spéc. v1.0</div>
    <nav class="nav" id="nav"></nav>
    <p class="rail-note">Le point prune signale une section modifiée depuis la
      révision de comparaison.</p>
  </aside>

  <main class="main">
    <header class="masthead">
      <div class="eyebrow">Spécification produit</div>
      <h1>Waterfall v1.0</h1>
      <p class="deck">La première version réellement utilisable. Ce document rassemble
        sous forme d'exigences numérotées et vérifiables des décisions aujourd'hui
        dispersées entre quatre spécifications partielles, des EPIC GitHub et des
        messages de commit.</p>
      <div class="stats" id="stats"></div>
    </header>

    <div class="controls">
      <span class="base">Comparé à <code id="baserev"></code></span>
      <label class="toggle"><input type="checkbox" id="hl" checked> Surligner les modifications</label>
      <label class="toggle"><input type="checkbox" id="only"> Ne montrer que les modifications</label>
    </div>

    <div class="changelog" id="changelog"></div>
    <div id="doc"></div>
    <p class="empty" id="empty">Aucune section modifiée à afficher.</p>
  </main>
</div>

<script id="source" type="text/plain">__MARKDOWN__</script>
<script id="changes" type="application/json">__CHANGES__</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/4.3.0/marked.min.js"></script>
<script>
(function(){
  "use strict";
  var md = document.getElementById("source").textContent;
  var data = JSON.parse(document.getElementById("changes").textContent);
  var doc = document.getElementById("doc");
  document.getElementById("baserev").textContent = data.base;

  if(!window.marked){                       // repli : la page reste lisible
    var raw = document.createElement("pre");
    raw.textContent = md; doc.appendChild(raw); return;
  }
  doc.innerHTML = marked.parse(md);

  function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
  function inline(s){
    return esc(s).replace(/`([^`]+)`/g,"<code>$1</code>")
                 .replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");
  }

  Array.prototype.forEach.call(doc.querySelectorAll("table"),function(t){
    var w=document.createElement("div"); w.className="tablewrap";
    t.parentNode.insertBefore(w,t); w.appendChild(t);
  });

  var LEVELS={"DOIT":"doit","DEVRAIT":"devrait","PEUT":"peut","ABANDONNÉE":"abandonnee"};
  var touched = data.changedRequirements || [];

  // Une exigence peut être citée en exemple avant d'être énoncée (§3.1 cite
  // EXG-AVA-012). L'ancre doit viser l'énoncé, pas la citation : on compte les
  // occurrences d'abord, et seule la dernière garde l'identifiant propre.
  var seen = {}, total = {};
  Array.prototype.forEach.call(doc.querySelectorAll("pre > code"),function(c){
    var m = c.textContent.match(/^(EXG-[A-Z]{3}-\d{3})/);
    if(m){ total[m[1]] = (total[m[1]]||0) + 1; }
  });

  Array.prototype.forEach.call(doc.querySelectorAll("pre > code"),function(code){
    var txt = code.textContent;
    if(!/^EXG-[A-Z]{3}-\d{3}/.test(txt)) return;
    var head=[], fields=[], cur=null;
    var fieldRe = /^\s{2}(Motif|Vérification|Source)\s+(.*)$/;
    txt.split("\n").forEach(function(l){
      var m = l.match(fieldRe);
      if(m){ cur={label:m[1],value:[m[2]]}; fields.push(cur); }
      else if(cur){ if(l.trim()) cur.value.push(l.trim()); }
      else if(l.trim()) head.push(l.trim());
    });
    var hm = head.join(" ").match(/^(EXG-[A-Z]{3}-\d{3})\s+—\s+([A-ZÉ]+)\s+—\s+([\s\S]*)$/);
    if(!hm) return;
    var id=hm[1], level=hm[2], statement=hm[3];
    var art = document.createElement("article");
    art.className = "req" + (touched.indexOf(id)>=0 ? " touched":"") +
                    (level==="ABANDONNÉE" ? " dropped":"");
    seen[id] = (seen[id]||0) + 1;
    art.id = (seen[id] < total[id]) ? id + "-cite" : id;
    var html = '<div class="req-head"><span class="req-code">'+id+'</span>'+
               '<span class="lvl '+(LEVELS[level]||"doit")+'">'+level+'</span>'+
               (touched.indexOf(id)>=0 ? '<span class="req-flag">modifiée</span>':'')+
               '</div><div class="req-statement">'+inline(statement)+'</div>';
    if(fields.length){
      html += '<dl class="req-fields">';
      fields.forEach(function(f){
        html += "<dt>"+f.label+"</dt><dd>"+inline(f.value.join(" "))+"</dd>";
      });
      html += "</dl>";
    }
    art.innerHTML = html;
    code.parentNode.parentNode.replaceChild(art, code.parentNode);
  });

  var h1 = doc.querySelector("h1");
  if(h1) h1.parentNode.removeChild(h1);

  var kids = Array.prototype.slice.call(doc.childNodes);
  var sections=[], cur=document.createElement("section");
  cur.dataset.title=""; cur.dataset.level="0";
  sections.push(cur); doc.appendChild(cur);
  kids.forEach(function(n){
    if(n.nodeType===1 && (n.tagName==="H2"||n.tagName==="H3")){
      cur = document.createElement("section");
      cur.dataset.title = n.textContent.trim();
      cur.dataset.level = n.tagName==="H2" ? "2":"3";
      sections.push(cur); doc.appendChild(cur); cur.appendChild(n);
    } else { cur.appendChild(n); }
  });

  var changed = data.changed||[], renum = data.renumbered||[];
  var nav = document.getElementById("nav"), slug=0;
  sections.forEach(function(s){
    var t = s.dataset.title;
    if(s.dataset.level==="0"){ s.id="preambule"; s.classList.add("intro"); return; }
    var isChanged = changed.indexOf(t)>=0, isRenum = renum.indexOf(t)>=0;
    s.id = "s"+(++slug);
    if(isChanged) s.classList.add("changed");
    var h = s.querySelector("h2,h3");
    if(h && (isChanged||isRenum)){
      var tag=document.createElement("span");
      tag.className="tag "+(isChanged?"mod":"renum");
      tag.textContent=isChanged?"modifié":"renuméroté";
      h.appendChild(tag);
    }
    var a=document.createElement("a");
    a.href="#"+s.id;
    a.className = (s.dataset.level==="3" ? "lvl3":"") + (isChanged ? " has-dot":"");
    var m = t.match(/^((?:\d+\.)?\d+|Annexe [A-Z])\s*[—.]?\s*(.*)$/);
    a.innerHTML = '<span class="num">'+(m?m[1]:"")+'</span><span>'+(m?(m[2]||t):t)+'</span>'+
                  (isChanged?'<span class="dot"></span>':'');
    nav.appendChild(a);
  });

  var html = "<h2>Modifications depuis votre relecture</h2><ol>";
  (data.commits||[]).forEach(function(c){
    html += "<li><code>"+c[0]+"</code><span>"+c[1]+"</span></li>";
  });
  html += "</ol>";
  if(touched.length){
    html += '<div class="chips"><b>Exigences touchées</b>';
    touched.forEach(function(id){ html += '<a class="chip" href="#'+id+'">'+id+'</a>'; });
    html += "</div>";
  }
  document.getElementById("changelog").innerHTML = html;

  document.getElementById("stats").innerHTML =
    '<div class="stat"><b>'+doc.querySelectorAll(".req").length+'</b><span>exigences</span></div>'+
    '<div class="stat"><b>'+data.chaptersWritten+'/'+data.chaptersPlanned+
      '</b><span>chapitres rédigés</span></div>'+
    '<div class="stat"><b>'+data.openQuestions+'</b><span>questions ouvertes</span></div>'+
    '<div class="stat"><b>'+changed.length+'</b><span>sections modifiées</span></div>';

  var hl=document.getElementById("hl"), only=document.getElementById("only");
  hl.addEventListener("change",function(){ document.body.classList.toggle("plain",!hl.checked); });
  only.addEventListener("change",function(){
    document.body.classList.toggle("only",only.checked);
    document.getElementById("empty").style.display =
      (only.checked && changed.length===0) ? "block":"none";
  });

  var links = {};
  Array.prototype.forEach.call(nav.querySelectorAll("a"),function(a){
    links[a.getAttribute("href").slice(1)]=a;
  });
  var obs = new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      var a = links[e.target.id];
      if(!a || !e.isIntersecting) return;
      Array.prototype.forEach.call(nav.querySelectorAll("a.on"),function(x){x.classList.remove("on");});
      a.classList.add("on");
    });
  },{rootMargin:"-10% 0px -80% 0px"});
  sections.forEach(function(s){ obs.observe(s); });
})();
</script>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    for name in ("base", "spec", "diff", "commits", "out"):
        ap.add_argument("--" + name, required=True)
    args = ap.parse_args()

    spec = open(args.spec, encoding="utf-8").read()
    if "</script" in spec.lower():
        raise SystemExit("le markdown contient une balise de fermeture script")

    # Un délimiteur de bloc manquant décale toute la suite du document sans rien
    # signaler : le texte se retrouve en préformaté et les exigences ne sont plus
    # reconnues. Le défaut est invisible à la relecture du markdown et saute aux
    # yeux sur la page, trop tard. On le refuse ici.
    fences = [ln for ln in spec.split("\n") if ln.strip() == "```"]
    if len(fences) % 2:
        raise SystemExit(
            "nombre impair de délimiteurs ``` (%d) : un bloc n'est pas fermé" % len(fences)
        )

    data = classify(spec, parse_touched(open(args.diff, encoding="utf-8").read()))
    data["base"] = args.base
    data["commits"] = []
    for line in open(args.commits, encoding="utf-8").read().strip().split("\n"):
        if not line:
            continue
        sha, subject = line.split("|", 1)
        subject = subject.replace("docs(v1.0): ", "")
        data["commits"].append([sha, subject[:1].upper() + subject[1:]])

    html = TEMPLATE.replace("__MARKDOWN__", spec)
    html = html.replace("__CHANGES__", json.dumps(data, ensure_ascii=False))
    open(args.out, "w", encoding="utf-8").write(html)

    print("sections modifiées :")
    for t in data["changed"]:
        print("   •", t)
    if data["renumbered"]:
        print("renumérotées :", ", ".join(data["renumbered"]))
    print("exigences touchées :", ", ".join(data["changedRequirements"]))
    print("écrit :", args.out)


if __name__ == "__main__":
    main()
