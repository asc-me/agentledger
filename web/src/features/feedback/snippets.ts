import { readableOn, type FeedbackConfig } from "./config";

/** Inline iframe + a tiny listener that auto-resizes it to the widget's content. */
export function inlineSnippet(embedUrl: string): string {
  return `<iframe id="al-feedback" src="${embedUrl}"
  width="440" height="520" style="border:0;max-width:100%" title="Feedback"></iframe>
<script>
window.addEventListener('message',function(e){
  var d=e.data; if(d&&d.__agentledger&&d.type==='resize'){
    var f=document.getElementById('al-feedback'); if(f) f.style.height=(d.height+4)+'px';
  }
});
</script>`;
}

/** A self-contained launcher: a floating button that opens the widget in a popover,
 *  auto-resizes it, and closes shortly after a successful submit. */
export function launcherSnippet(embedUrl: string, cfg: FeedbackConfig): string {
  const j = (v: string) => JSON.stringify(v);
  return `<script>
(function(){
  var U=${j(embedUrl)}, P=${j(cfg.position)}, A=${j(cfg.accent)}, L=${j(cfg.launcherLabel)}, TXT=${j(readableOn(cfg.accent))};
  var open=false, frame, btn;
  function side(x){ return (P==='bottom-left'?'left:':'right:')+x; }
  function mk(){
    btn=document.createElement('button'); btn.textContent=L; btn.setAttribute('aria-label',L);
    btn.style.cssText='position:fixed;z-index:2147483000;bottom:20px;'+side('20px')+';background:'+A+';color:'+TXT+';border:0;border-radius:999px;padding:11px 18px;font:600 14px/1 system-ui,sans-serif;cursor:pointer;box-shadow:0 6px 22px rgba(0,0,0,.22)';
    btn.onclick=toggle; document.body.appendChild(btn); window.addEventListener('message',onMsg);
  }
  function toggle(){ open?close():openPanel(); }
  function openPanel(){
    frame=document.createElement('iframe');
    frame.src=U+(U.indexOf('?')>-1?'&':'?')+'ref='+encodeURIComponent(location.href); frame.title='Feedback';
    frame.style.cssText='position:fixed;z-index:2147483000;bottom:74px;'+side('20px')+';width:min(440px,calc(100vw - 40px));height:520px;max-height:calc(100vh - 110px);border:0;border-radius:14px;box-shadow:0 16px 50px rgba(0,0,0,.28);background:transparent';
    document.body.appendChild(frame); open=true;
  }
  function close(){ if(frame){frame.remove();frame=null;} open=false; }
  function onMsg(e){
    var d=e.data; if(!d||!d.__agentledger) return;
    if(d.type==='resize'&&frame){ frame.style.height=Math.min(d.height+4, innerHeight-110)+'px'; }
    if(d.type==='submitted'){ setTimeout(close,1800); }
  }
  if(document.readyState!=='loading') mk(); else addEventListener('DOMContentLoaded',mk);
})();
</script>`;
}
