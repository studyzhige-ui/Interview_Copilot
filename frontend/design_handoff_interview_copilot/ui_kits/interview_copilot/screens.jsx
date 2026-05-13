/* global React */
const { useState, useRef, useEffect } = React;
const { I, Logo, Btn, Field, Pill } = window.UIKit;

/* ============ AUTH ============ */
function Auth({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("user@example.com");
  const [pw, setPw] = useState("••••••");
  return (
    <div data-screen-label="01 Auth" style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: "linear-gradient(135deg, var(--color-cream-50) 0%, #fff 50%, var(--color-sand-100) 100%)",
      padding: 24
    }}>
      <div className="fade-in" style={{
        width: 420, background: "#fff", borderRadius: 20, padding: 36,
        boxShadow: "var(--shadow-lg)", border: "1px solid var(--color-stone-200)"
      }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, marginBottom: 24 }}>
          <Logo size={48}/>
          <div style={{ fontSize: 20, fontWeight: 600, color: "var(--color-stone-800)" }}>Interview Copilot</div>
          <div style={{ fontSize: 13, color: "var(--color-stone-500)" }}>让每一次面试都成为进步的阶梯</div>
        </div>
        <div style={{ display: "flex", padding: 3, background: "var(--color-stone-100)", borderRadius: 10, marginBottom: 22 }}>
          {[["login", "登录"], ["signup", "注册"]].map(([k, l]) => (
            <button key={k} onClick={() => setMode(k)}
              style={{ flex: 1, padding: "8px 12px", borderRadius: 8, border: "none", fontSize: 13, fontWeight: 500,
                cursor: "pointer", background: mode === k ? "#fff" : "transparent",
                color: mode === k ? "var(--color-stone-800)" : "var(--color-stone-500)",
                boxShadow: mode === k ? "var(--shadow-xs)" : "none", transition: "all 150ms" }}>{l}</button>
          ))}
        </div>
        <Field label="邮箱" icon={I.mail} value={email} onChange={setEmail} placeholder="you@email.com"/>
        <Field label="密码" type="password" icon={I.lock} value={pw} onChange={setPw}
          hint={mode === "signup" ? "至少 6 位" : null}/>
        {mode === "signup" && <Field label="确认密码" type="password" icon={I.lock} value={pw} onChange={setPw}/>}
        <div style={{ marginTop: 8 }}>
          <Btn full size="lg" onClick={onLogin}>{mode === "login" ? "登 录" : "注 册"}</Btn>
        </div>
        <div style={{ marginTop: 18, fontSize: 12, color: "var(--color-stone-500)", textAlign: "center" }}>
          {mode === "login"
            ? <>还没有账号？<a onClick={() => setMode("signup")} style={{ color: "var(--color-primary-600)", cursor: "pointer" }}>立即注册</a></>
            : <>已有账号？<a onClick={() => setMode("login")} style={{ color: "var(--color-primary-600)", cursor: "pointer" }}>返回登录</a></>}
        </div>
      </div>
    </div>
  );
}

/* ============ REVIEW ============ */
const mkQA = (q, a, s) => ({ q, a, s });
const SEED_QA = [
  mkQA(
    "介绍一下你最近主导的项目，重点说说技术选型的考量。",
    "我们做的是一个面试辅助平台。后端选了 FastAPI 是因为团队对类型注解友好，前端 React + Vite 上手快。RAG 部分用了 LlamaIndex，向量库选了 Milvus...",
    "可以先用一句话定位项目（目标用户+核心价值），再展开技术选型，每个选型给一个量化指标（QPS / 延迟 / 团队成本）。结尾建议补充一个'回头看会怎么改'。",
  ),
  mkQA(
    "为什么选 Milvus 而不是 Qdrant 或 pgvector？",
    "数据规模和热点写入决定的。我们要支持分钟级数千条切片入库，pgvector 在 10w+ 后 ANN 召回耗时上升明显...",
    "把三者放在同一张表里对比：写入吞吐、ANN 召回 P95、运维成本、生态。再说明你们 10w+ 量级实测时 pgvector 的 P95 从 X ms 升到 Y ms，给出可复现的实验条件。",
  ),
  mkQA(
    "Whisper 的转录延迟你们怎么优化？",
    "用 Faster-Whisper 跑 distil-large-v3，开 chunk_length=15，streaming 分段...",
    "回答可以分成三层：模型层（distil + INT8 量化）、调度层（chunk + 流式 + VAD 切分）、工程层（GPU 复用 / 批处理）。最后给一个端到端延迟数字，例如 3s 输入到首字 X ms。",
  ),
];
const SEED_SESSIONS = [
  { id: 1, title: "字节后端 · 二面", date: "5/08", tag: "Backend",   qa: SEED_QA },
  { id: 2, title: "腾讯算法 · 一面", date: "5/04", tag: "Algorithm", qa: SEED_QA.slice(0, 2) },
  { id: 3, title: "Mock · 系统设计",  date: "4/29", tag: "System",    qa: [] },
  { id: 4, title: "美团数据 · HR",    date: "4/22", tag: "HR",        qa: SEED_QA.slice(0, 1) },
];

function Review() {
  const [sessions, setSessions] = useState(SEED_SESSIONS);
  const [active, setActive] = useState(1);
  const [renaming, setRenaming] = useState(null);
  const [openMenu, setOpenMenu] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [audioUp, setAudioUp] = useState({});
  const [resumeUp, setResumeUp] = useState({});
  const [jdUp, setJdUp] = useState({});
  const audioRef = useRef(null);
  const resumeRef = useRef(null);
  const jdRef = useRef(null);
  const tryAnalyze = (sid, audio, resume) => {
    if (!audio || !resume) return;
    setUploading(true);
    setTimeout(() => {
      setSessions(ps => ps.map(s => s.id === sid ? { ...s, qa: SEED_QA } : s));
      setUploading(false);
    }, 1400);
  };
  const onUpload = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const name = f.name;
    const nextAudio = { ...audioUp, [active]: name };
    setAudioUp(nextAudio);
    tryAnalyze(active, name, resumeUp[active]);
    e.target.value = "";
  };
  const onResumeUp = (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    const name = f.name; const next = { ...resumeUp, [active]: name }; setResumeUp(next);
    tryAnalyze(active, audioUp[active], name);
    e.target.value = "";
  };
  const onJdUp = (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    setJdUp({ ...jdUp, [active]: f.name });
    e.target.value = "";
  };

  const cur = sessions.find(s => s.id === active);
  const setQA = (idx, patch) => setSessions(ps => ps.map(s => s.id === active
    ? { ...s, qa: s.qa.map((p, i) => i === idx ? { ...p, ...patch } : p) }
    : s));

  const newSession = () => {
    const id = Date.now();
    setSessions(p => [{ id, title: "新建面试", date: "今天", tag: "New", qa: [] }, ...p]);
    setActive(id);
  };
  const delSession = (id) => {
    setOpenMenu(null);
    setSessions(p => {
      const next = p.filter(s => s.id !== id);
      if (active === id) setActive(next[0]?.id ?? null);
      return next;
    });
  };

  return (
    <div data-screen-label="02 Review" style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {/* Session list */}
      <aside style={{ width: 260, background: "#fff", borderRight: "1px solid var(--color-stone-200)",
        display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div style={{ padding: "16px 16px 12px", borderBottom: "1px solid var(--color-stone-200)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-stone-800)" }}>我的面试</div>
            <button onClick={newSession} title="新建"
              style={{ width: 28, height: 28, borderRadius: 8, border: "none",
              background: "var(--color-primary-50)", color: "var(--color-primary-600)", cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center" }}>{I.plus}</button>
          </div>
          <div style={{ position: "relative" }}>
            <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)",
              color: "var(--color-stone-400)" }}>{I.search}</span>
            <input placeholder="搜索面试记录"
              style={{ width: "100%", padding: "8px 10px 8px 32px", fontSize: 12,
                background: "var(--color-stone-50)", border: "1px solid var(--color-stone-200)",
                borderRadius: 10, outline: "none", color: "var(--color-stone-700)" }}/>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: 8 }}>
          {sessions.map(s => {
            const act = s.id === active;
            return (
              <div key={s.id} onClick={() => setActive(s.id)}
                style={{ position: "relative", padding: "10px 12px", borderRadius: 10, cursor: "pointer", marginBottom: 4,
                  background: act ? "var(--color-primary-50)" : "transparent",
                  border: act ? "1px solid var(--color-primary-100)" : "1px solid transparent" }}>
                {renaming === s.id ? (
                  <input autoFocus defaultValue={s.title} onBlur={e => {
                    setSessions(p => p.map(x => x.id === s.id ? { ...x, title: e.target.value } : x));
                    setRenaming(null);
                  }} onKeyDown={e => e.key === "Enter" && e.target.blur()}
                  style={{ width: "100%", fontSize: 13, padding: 2, border: "1px solid var(--color-primary-300)",
                    borderRadius: 6, outline: "none" }}/>
                ) : (
                  <>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                      <div style={{ fontSize: 13, fontWeight: act ? 600 : 500, flex: 1, minWidth: 0,
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        color: act ? "var(--color-primary-700)" : "var(--color-stone-800)" }}>{s.title}</div>
                      <button onClick={e => { e.stopPropagation(); setOpenMenu(openMenu === s.id ? null : s.id); }}
                        title="更多"
                        style={{ width: 22, height: 22, borderRadius: 6, border: "none",
                          background: "transparent", color: "var(--color-stone-500)", cursor: "pointer",
                          display: "flex", alignItems: "center", justifyContent: "center" }}>{I.more}</button>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                      <span style={{ fontSize: 11, color: "var(--color-stone-500)" }}>{s.date} · {s.qa.length} 题</span>
                      <Pill tone="sand">{s.tag}</Pill>
                    </div>
                    {openMenu === s.id && (
                      <div onClick={e => e.stopPropagation()}
                        style={{ position: "absolute", top: 36, right: 8, width: 140, padding: 4,
                          background: "#fff", border: "1px solid var(--color-stone-200)", borderRadius: 10,
                          boxShadow: "var(--shadow-lg)", zIndex: 20 }}>
                        <div onClick={() => { setRenaming(s.id); setOpenMenu(null); }} style={menuItem()}>
                          <span style={{ color: "var(--color-stone-500)" }}>{I.pencil}</span>重命名
                        </div>
                        <div onClick={() => delSession(s.id)} style={menuItem("danger")}>
                          <span>{I.trash}</span>删除
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
      </aside>

      {/* Center */}
      <section style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "28px 36px" }}>
        <div style={{ marginBottom: 18 }}>
          <div className="eyebrow">复盘</div>
          <h2 style={{ margin: "6px 0 0" }}>{cur?.title ?? "选择或新建一个 session"}</h2>
        </div>

        <input ref={audioRef}  type="file" accept="audio/*,video/*" onChange={onUpload} style={{ display: "none" }}/>
        <input ref={resumeRef} type="file" accept=".pdf,.doc,.docx"  onChange={onResumeUp} style={{ display: "none" }}/>
        <input ref={jdRef}     type="file" accept=".txt,.md"          onChange={onJdUp} style={{ display: "none" }}/>

        {!cur ? null : cur.qa.length === 0 ? (
          uploading ? (
            <div style={{ padding: 40, borderRadius: 16, border: "1px solid var(--color-stone-200)",
              background: "#fff", textAlign: "center", boxShadow: "var(--shadow-sm)" }}>
              <div style={{ fontSize: 14, color: "var(--color-primary-600)", fontFamily: "var(--font-mono)" }}>● 正在转录与分析…</div>
            </div>
          ) : (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, marginBottom: 18 }}>
                {[
                  { k: "audio",  title: "上传音视频", desc: "MP3 / MP4 / WAV · 自动转录", icon: I.upload, done: audioUp[active],  ref: audioRef,  required: true },
                  { k: "resume", title: "上传简历",   desc: "PDF / DOCX · 用于分析背景",   icon: I.file,   done: resumeUp[active], ref: resumeRef, required: true },
                  { k: "jd",     title: "上传岗位 JD",desc: "TXT / MD · 可选，定位方向",   icon: I.book,   done: jdUp[active],     ref: jdRef,     required: false },
                ].map(c => (
                  <div key={c.k} onClick={() => c.ref.current?.click()} style={{
                    padding: 20, background: "#fff", borderRadius: 16,
                    border: "2px dashed " + (c.done ? "var(--color-success-500)" : c.required ? "var(--color-primary-300)" : "var(--color-stone-300)"),
                    cursor: "pointer", transition: "all 150ms"
                  }}>
                    <div style={{ width: 40, height: 40, borderRadius: 10, marginBottom: 12,
                      background: c.done ? "var(--color-success-50)" : "var(--color-primary-50)",
                      color: c.done ? "var(--color-success-700)" : "var(--color-primary-600)",
                      display: "flex", alignItems: "center", justifyContent: "center" }}>
                      {c.done ? I.check : c.icon}
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-stone-800)",
                      display: "flex", alignItems: "center", gap: 6 }}>
                      {c.title}
                      {c.required && <span style={{ fontSize: 10, color: "var(--color-danger-500)" }}>*</span>}
                    </div>
                    <div style={{ fontSize: 12, color: "var(--color-stone-500)", marginTop: 4 }}>{c.desc}</div>
                    {c.done && <div style={{ fontSize: 11, color: "var(--color-success-700)", marginTop: 8,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.done}</div>}
                  </div>
                ))}
              </div>
              <div style={{ padding: "14px 18px", borderRadius: 12, background: "var(--color-primary-50)",
                color: "var(--color-primary-700)", fontSize: 13, display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--color-primary-500)" }}></span>
                需要音视频 + 简历才能开始分析；岗位 JD 可选，提供后分析会更精准。
              </div>
            </div>
          )
        ) : (
          <ReportQATabs qa={cur.qa} setQA={setQA}/>
        )}
      </section>

      <ChatPanel sessionId={cur.id} sessionTitle={cur.title} hasQA={(cur.qa||[]).length > 0}/>
    </div>
  );
}

const menuItem = (tone) => ({
  display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: 6,
  fontSize: 12, cursor: "pointer",
  color: tone === "danger" ? "var(--color-danger-500)" : "var(--color-stone-700)",
});

function QAItem({ idx, item, onChange }) {
  const [editingQ, setEditingQ] = useState(false);
  const [editingA, setEditingA] = useState(false);
  const [openS, setOpenS] = useState(false);
  return (
    <article style={{ background: "#fff", borderRadius: 16, padding: 20,
      border: "1px solid var(--color-stone-200)", boxShadow: "var(--shadow-sm)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <Pill tone="primary">Q{idx + 1}</Pill>
        <span style={{ fontSize: 12, color: "var(--color-stone-500)" }}>面试官</span>
        <button onClick={() => setEditingQ(e => !e)} title="编辑"
          style={{ marginLeft: "auto", width: 24, height: 24, borderRadius: 6, border: "none",
            background: "transparent", color: "var(--color-stone-400)", cursor: "pointer",
            display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{I.pencil}</button>
      </div>
      {editingQ ? (
        <textarea value={item.q} onChange={e => onChange({ q: e.target.value })} rows={2}
          onBlur={() => setEditingQ(false)} autoFocus
          style={editableTextarea(15, 500)}/>
      ) : (
        <div onDoubleClick={() => setEditingQ(true)}
          style={{ fontSize: 15, fontWeight: 500, color: "var(--color-stone-800)",
            lineHeight: 1.55, marginBottom: 14, cursor: "text" }}>{item.q}</div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <Pill tone="success">A</Pill>
        <span style={{ fontSize: 12, color: "var(--color-stone-500)" }}>你的回答 · 可编辑</span>
        <button onClick={() => setEditingA(e => !e)} title="编辑"
          style={{ marginLeft: "auto", width: 24, height: 24, borderRadius: 6, border: "none",
            background: "transparent", color: "var(--color-stone-400)", cursor: "pointer",
            display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{I.pencil}</button>
      </div>
      {editingA ? (
        <textarea value={item.a} onChange={e => onChange({ a: e.target.value })} rows={4}
          onBlur={() => setEditingA(false)} autoFocus
          style={{ ...editableTextarea(14, 400), fontFamily: "var(--font-mono)", lineHeight: 1.6 }}/>
      ) : (
        <div onDoubleClick={() => setEditingA(true)}
          style={{ fontSize: 14, color: "var(--color-stone-700)", lineHeight: 1.6,
            fontFamily: "var(--font-mono)", background: "var(--color-stone-50)",
            padding: 12, borderRadius: 10, cursor: "text" }}>{item.a}</div>
      )}

      {/* Collapsible AI suggestion */}
      <div style={{ marginTop: 14, borderTop: "1px solid var(--color-stone-100)" }}>
        <button onClick={() => setOpenS(s => !s)}
          style={{ display: "flex", alignItems: "center", gap: 8, width: "100%",
            padding: "12px 0 0", border: "none", background: "transparent", cursor: "pointer",
            fontSize: 13, fontWeight: 500, color: "var(--color-primary-700)",
            fontFamily: "var(--font-sans)", textAlign: "left" }}>
          <span style={{ transform: openS ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 180ms var(--ease-out)", display: "inline-flex" }}>{I.chev}</span>
          <span>优化回答</span>
          {!openS && <span style={{ fontSize: 11, color: "var(--color-stone-400)", fontWeight: 400 }}>· 点击展开</span>}
        </button>
        {openS && (
          <div className="fade-in" style={{ marginTop: 10, padding: 14, borderRadius: 12,
            background: "var(--color-primary-50)", border: "1px solid var(--color-primary-100)",
            color: "var(--color-stone-800)", fontSize: 13, lineHeight: 1.65 }}>
            {item.s}
          </div>
        )}
      </div>
    </article>
  );
}
const editableTextarea = (fs, fw) => ({
  width: "100%", padding: 10, fontSize: fs, fontWeight: fw,
  color: "var(--color-stone-800)", background: "var(--color-stone-50)",
  border: "1px solid var(--color-primary-200)", borderRadius: 10,
  outline: "none", resize: "vertical", marginBottom: 14, fontFamily: "var(--font-sans)",
  boxSizing: "border-box",
});

function ChatTabs({ chats, curId, onPick, onRename, onDelete, onNew }) {
  const [editing, setEditing] = useState(null);
  const [hover, setHover] = useState(null);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "10px 12px",
      borderBottom: "1px solid var(--color-stone-200)", overflowX: "auto" }}>
      {chats.map(c => {
        const act = c.id === curId;
        const showActions = act || hover === c.id;
        return (
          <div key={c.id} onMouseEnter={() => setHover(c.id)} onMouseLeave={() => setHover(null)}
            style={{ position: "relative", flexShrink: 0 }}>
            {editing === c.id ? (
              <input autoFocus defaultValue={c.name}
                onBlur={e => { onRename(c.id, e.target.value.trim() || c.name); setEditing(null); }}
                onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setEditing(null); }}
                style={{ width: 110, padding: "4px 10px", fontSize: 12, borderRadius: 999,
                  border: "1px solid var(--color-accent-300)", outline: "none",
                  background: "#fff", fontFamily: "var(--font-sans)" }}/>
            ) : (
              <div onDoubleClick={() => setEditing(c.id)}
                style={{ display: "inline-flex", alignItems: "center", gap: 4,
                  paddingLeft: 12, paddingRight: showActions ? 4 : 12, paddingTop: 4, paddingBottom: 4,
                  borderRadius: 999, cursor: "pointer", transition: "all 120ms",
                  border: "1px solid " + (act ? "var(--color-primary-300)" : "var(--color-stone-200)"),
                  background: act ? "var(--color-primary-50)" : "#fff" }}>
                <span onClick={() => onPick(c.id)}
                  style={{ fontSize: 12, fontWeight: act ? 600 : 500,
                    color: act ? "var(--color-primary-700)" : "var(--color-stone-700)",
                    fontFamily: "var(--font-sans)" }}>{c.name}</span>
                {showActions && (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 1, marginLeft: 2 }}>
                    <button onClick={(e) => { e.stopPropagation(); setEditing(c.id); }}
                      title="重命名"
                      style={tabIconBtn}>{I.pencil}</button>
                    {chats.length > 1 && (
                      <button onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
                        title="删除"
                        style={tabIconBtn}>✕</button>
                    )}
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}
      <button onClick={onNew} title="新对话"
        style={{ width: 26, height: 26, borderRadius: 999, border: "1px dashed var(--color-stone-300)",
          background: "transparent", color: "var(--color-stone-500)", cursor: "pointer",
          display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
          fontSize: 14, lineHeight: 1 }}>+</button>
    </div>
  );
}
const tabIconBtn = {
  width: 20, height: 20, padding: 0, border: "none", background: "transparent",
  borderRadius: 999, cursor: "pointer", display: "inline-flex", alignItems: "center",
  justifyContent: "center", color: "var(--color-stone-500)", fontSize: 11, lineHeight: 1,
};

function ChatPanel({ sessionId, sessionTitle, hasQA }) {
  const [agent, setAgent] = useState(false);
  const [model, setModel] = useState("DeepSeek V4 Flash");
  const [showMenu, setShowMenu] = useState(false);
  const fileRef = useRef(null);
  const [attached, setAttached] = useState([]);
  const [chatsBySession, setChatsBySession] = useState({});
  const [activeChat, setActiveChat] = useState({});
  const initSeed = (withQA) => (withQA
    ? [{ role: "ai", text: "嗨，我已经读完这次面试。最弱的一题是关于 Milvus 选型的回答—— 你想从哪里开始复盘？" }]
    : []);
  const ensure = (sid, withQA) => {
    if (chatsBySession[sid]) return;
    const cid = "c-" + Math.random().toString(36).slice(2, 7);
    setChatsBySession(s => ({ ...s, [sid]: [{ id: cid, name: "对话 1", msgs: initSeed(withQA) }] }));
    setActiveChat(a => ({ ...a, [sid]: cid }));
  };
  React.useEffect(() => { if (sessionId) ensure(sessionId, hasQA); }, [sessionId]);
  // when upload completes (hasQA flips true), seed the welcome message if empty
  React.useEffect(() => {
    if (!sessionId || !hasQA) return;
    setChatsBySession(s => {
      const list = s[sessionId];
      if (!list) return s;
      const cid = activeChat[sessionId] || list[0]?.id;
      const cur = list.find(c => c.id === cid);
      if (!cur || cur.msgs.length > 0) return s;
      return { ...s, [sessionId]: list.map(c => c.id === cid ? { ...c, msgs: initSeed(true) } : c) };
    });
  }, [hasQA, sessionId]);
  const chats = chatsBySession[sessionId] || [];
  const curId = activeChat[sessionId];
  const cur = chats.find(c => c.id === curId) || chats[0];
  const msgs = cur?.msgs || [];
  const setMsgs = (fn) => setChatsBySession(s => ({
    ...s,
    [sessionId]: (s[sessionId] || []).map(c => c.id === curId ? { ...c, msgs: typeof fn === "function" ? fn(c.msgs) : fn } : c),
  }));
  const newChat = () => {
    const cid = "c-" + Math.random().toString(36).slice(2, 7);
    setChatsBySession(s => ({ ...s, [sessionId]: [...(s[sessionId] || []), { id: cid, name: `对话 ${(s[sessionId]||[]).length + 1}`, msgs: initSeed(hasQA) }] }));
    setActiveChat(a => ({ ...a, [sessionId]: cid }));
  };
  const [draft, setDraft] = useState("");
  const send = () => {
    if (!draft.trim()) return;
    setMsgs(m => [...m, { role: "me", text: draft }, { role: "ai", text: "（AI 正在生成回答…）" }]);
    setDraft("");
  };
  const models = ["DeepSeek V4 Flash", "DeepSeek V4 Pro", "GPT-4o", "Claude Sonnet 4.5", "Qwen3-Max"];
  return (
    <aside style={{ width: 360, background: "#fff", borderLeft: "1px solid var(--color-stone-200)",
      display: "flex", flexDirection: "column", flexShrink: 0 }}>
      <div style={{ padding: "14px 16px 0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-stone-800)" }}>复盘对话</div>
          <div style={{ fontSize: 11, color: "var(--color-stone-500)", marginTop: 2 }}>{sessionTitle || "基于本次记录"}</div>
        </div>
        <div style={{ position: "relative" }}>
          <button onClick={() => setShowMenu(s => !s)}
            style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 10px", borderRadius: 8,
              border: "1px solid var(--color-stone-200)", background: "var(--color-stone-50)",
              fontSize: 11, color: "var(--color-stone-700)", cursor: "pointer", fontFamily: "var(--font-mono)" }}>
            {I.sparkle}<span>{model}</span>{I.chev}
          </button>
          {showMenu && (
            <div style={{ position: "absolute", top: "calc(100% + 4px)", right: 0, width: 200, padding: 4,
              background: "#fff", border: "1px solid var(--color-stone-200)", borderRadius: 10,
              boxShadow: "var(--shadow-lg)", zIndex: 10 }}>
              {models.map(m => (
                <div key={m} onClick={() => { setModel(m); setShowMenu(false); }}
                  style={{ padding: "6px 10px", borderRadius: 6, fontSize: 12, cursor: "pointer",
                    color: m === model ? "var(--color-primary-700)" : "var(--color-stone-700)",
                    background: m === model ? "var(--color-primary-50)" : "transparent",
                    fontFamily: "var(--font-mono)" }}>{m}</div>
              ))}
            </div>
          )}
        </div>
      </div>
      <ChatTabs chats={chats} curId={curId}
        onPick={cid => setActiveChat(a => ({ ...a, [sessionId]: cid }))}
        onRename={(cid, name) => setChatsBySession(s => ({ ...s, [sessionId]: s[sessionId].map(c => c.id===cid?{...c, name}:c) }))}
        onDelete={cid => setChatsBySession(s => {
          const next = (s[sessionId] || []).filter(c => c.id !== cid);
          if (curId === cid) setActiveChat(a => ({ ...a, [sessionId]: next[0]?.id }));
          return { ...s, [sessionId]: next };
        })}
        onNew={newChat}/>
      <div style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        {msgs.length === 0 && (
          <div style={{ margin: "auto", textAlign: "center", padding: 24, color: "var(--color-stone-400)" }}>
            <div style={{ width: 44, height: 44, margin: "0 auto 12px", borderRadius: 14,
              background: "var(--color-stone-100)", color: "var(--color-stone-400)",
              display: "flex", alignItems: "center", justifyContent: "center" }}>{I.sparkle}</div>
            <div style={{ fontSize: 13, color: "var(--color-stone-500)", marginBottom: 4, fontWeight: 500 }}>等待上传完成</div>
            <div style={{ fontSize: 11, lineHeight: 1.6 }}>上传并解析音视频后，<br/>这里会给出复盘建议</div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} style={{ display: "flex", justifyContent: m.role === "me" ? "flex-end" : "flex-start" }}>
            <div style={{ maxWidth: "85%", padding: "10px 14px", borderRadius: 14, fontSize: 13, lineHeight: 1.55,
              background: m.role === "me" ? "var(--color-primary-500)" : "var(--color-stone-100)",
              color: m.role === "me" ? "#fff" : "var(--color-stone-800)",
              borderBottomRightRadius: m.role === "me" ? 4 : 14,
              borderBottomLeftRadius: m.role === "me" ? 14 : 4 }}>{m.text}</div>
          </div>
        ))}
      </div>
      <div style={{ padding: 12, borderTop: "1px solid var(--color-stone-200)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
          <button onClick={() => setAgent(a => !a)}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px",
              borderRadius: 999, border: "1px solid " + (agent ? "var(--color-primary-300)" : "var(--color-stone-200)"),
              background: agent ? "var(--color-primary-50)" : "transparent",
              color: agent ? "var(--color-primary-700)" : "var(--color-stone-600)",
              fontSize: 11, fontWeight: 500, cursor: "pointer", letterSpacing: 0.04 }}>
            <span style={{ width: 6, height: 6, borderRadius: 999,
              background: agent ? "var(--color-primary-500)" : "var(--color-stone-400)" }}></span>
            {agent ? "AGENT" : "CHAT"}
          </button>
          <input ref={fileRef} type="file" multiple style={{display:"none"}}
            onChange={e => { const fs = [...(e.target.files||[])].map(f=>f.name); if (fs.length) setAttached(a=>[...a,...fs]); e.target.value=""; }}/>
          <button onClick={()=>fileRef.current?.click()}
            title="附加文件"
            style={{ padding: 6, borderRadius: 8, border: "none", background: "transparent",
            color: "var(--color-stone-500)", cursor: "pointer" }}>{I.clip}</button>
          <span style={{ fontSize: 11, color: "var(--color-stone-400)", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
            {attached.length ? attached.join(" · ") : "点 📎 附加简历 / 文档"}
          </span>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "flex-end" }}>
          <textarea value={draft} onChange={e => setDraft(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
            placeholder="问点什么 · Shift+Enter 换行" rows={2}
            style={{ flex: 1, resize: "none", padding: "8px 12px", fontSize: 13,
              background: "var(--color-stone-50)", border: "1px solid var(--color-stone-200)",
              borderRadius: 10, outline: "none", color: "var(--color-stone-800)" }}/>
          <button onClick={send} style={{ width: 36, height: 36, borderRadius: 10, border: "none",
            background: "var(--color-primary-500)", color: "#fff", cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center" }}>{I.send}</button>
        </div>
      </div>
    </aside>
  );
}

/* ============ MOCK INTERVIEW ============ */
function Mock() {
  const [phase, setPhase] = useState("setup");
  const [resume, setResume] = useState(false);
  const [jd, setJd] = useState(false);
  const resumeInput = useRef(null);
  const jdInput = useRef(null);
  const [recording, setRecording] = useState(false);
  const [turns, setTurns] = useState([
    { who: "ai", text: "你好，我看到你的简历里写了 Interview Copilot，请先做一个 90 秒的项目介绍。" },
    { who: "me", text: "好的。Interview Copilot 是一个面向求职者的面试辅助平台，核心能力分为复盘和模拟两部分..." },
    { who: "ai", text: "听起来不错。我注意到你提到 Milvus，能展开讲讲你们的分片和索引策略吗？" },
  ]);
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollTo({ top: 9e9, behavior: "smooth" }); }, [turns.length]);

  if (phase === "setup") {
    const slots = [
      { k: "resume", title: "上传简历",     desc: "PDF / DOCX · 用于个性化提问",     done: resume, ref: resumeInput, icon: I.file, accept: ".pdf,.doc,.docx", set: setResume },
      { k: "jd",     title: "上传岗位 JD",  desc: "TXT / MD · 仅支持文本，定位提问方向", done: jd,     ref: jdInput,     icon: I.book, accept: ".txt,.md",         set: setJd },
    ];
    const ready = resume && jd;
    return (
      <div data-screen-label="03 Mock Setup" style={{ flex: 1, overflowY: "auto" }}>
        <div style={{ maxWidth: 760, margin: "0 auto", padding: "64px 36px",
          display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div className="eyebrow">模拟面试</div>
          <h2 style={{ margin: "6px 0 6px", textAlign: "center" }}>开始之前，先准备两份材料</h2>
          <p style={{ color: "var(--color-stone-500)", marginTop: 0, marginBottom: 32, textAlign: "center" }}>
            上传简历和岗位 JD 后，AI 面试官会根据你的背景定制问题。
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, width: "100%" }}>
            {slots.map(c => (
              <React.Fragment key={c.k}>
                <input ref={c.ref} type="file" accept={c.accept} style={{display:"none"}}
                  onChange={e => e.target.files?.[0] && c.set(true)}/>
                <div onClick={() => c.ref.current?.click()} style={{
                  padding: 22, background: "#fff", borderRadius: 16,
                  border: "2px dashed " + (c.done ? "var(--color-success-500)" : "var(--color-stone-300)"),
                  cursor: "pointer", transition: "all 150ms"
                }}>
                  <div style={{ width: 44, height: 44, borderRadius: 12, marginBottom: 14,
                    background: c.done ? "var(--color-success-50)" : "var(--color-primary-50)",
                    color: c.done ? "var(--color-success-700)" : "var(--color-primary-600)",
                    display: "flex", alignItems: "center", justifyContent: "center" }}>
                    {c.done ? I.check : c.icon}
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: "var(--color-stone-800)" }}>{c.title}</div>
                  <div style={{ fontSize: 12, color: "var(--color-stone-500)", marginTop: 4 }}>{c.desc}</div>
                  {c.done && <div style={{ fontSize: 12, color: "var(--color-success-700)", marginTop: 10 }}>已上传 · 点击替换</div>}
                </div>
              </React.Fragment>
            ))}
          </div>
          <div style={{ marginTop: 32, display: "flex", alignItems: "center", justifyContent: "center", gap: 12 }}>
            <Btn size="lg" onClick={() => ready && setPhase("live")} icon={I.mic}>
              {ready ? "开始模拟面试" : "请先完成上传"}
            </Btn>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div data-screen-label="03 Mock Live" style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <header style={{ padding: "16px 36px", borderBottom: "1px solid var(--color-stone-200)",
        display: "flex", alignItems: "center", justifyContent: "space-between", background: "#fff" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: "var(--color-danger-500)" }}></span>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-stone-800)" }}>模拟面试进行中</span>
          <Pill tone="sand">后端开发 · 字节</Pill>
        </div>
        <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--color-stone-500)" }}>12:48</div>
      </header>

      <div ref={endRef} style={{ flex: 1, overflowY: "auto", padding: "28px 0" }}>
        <div style={{ maxWidth: 760, margin: "0 auto", padding: "0 28px",
          display: "flex", flexDirection: "column", gap: 16 }}>
          {turns.map((t, i) => (
            <div key={i} className="fade-in" style={{ display: "flex",
              justifyContent: t.who === "me" ? "flex-end" : "flex-start" }}>
              <div style={{ maxWidth: "78%" }}>
                <div style={{ fontSize: 11, color: "var(--color-stone-500)", marginBottom: 4,
                  textAlign: t.who === "me" ? "right" : "left", fontFamily: "var(--font-mono)" }}>
                  {t.who === "me" ? "你" : "AI 面试官"}
                </div>
                <div style={{
                  padding: "14px 18px", borderRadius: 16, fontSize: 15, lineHeight: 1.6,
                  background: t.who === "me" ? "var(--color-primary-500)" : "#fff",
                  color: t.who === "me" ? "#fff" : "var(--color-stone-800)",
                  border: t.who === "me" ? "none" : "1px solid var(--color-stone-200)",
                  boxShadow: t.who === "me" ? "none" : "var(--shadow-sm)",
                }}>{t.text}</div>
              </div>
            </div>
          ))}
          {recording && (
            <div className="fade-in" style={{ display: "flex", justifyContent: "flex-end" }}>
              <div style={{ padding: "10px 14px", borderRadius: 12, background: "var(--color-primary-50)",
                color: "var(--color-primary-700)", fontSize: 13, fontFamily: "var(--font-mono)" }}>
                ● 录音中 · 转录…
              </div>
            </div>
          )}
        </div>
      </div>

      <footer style={{ padding: "20px 36px 28px", display: "flex", alignItems: "center",
        justifyContent: "center", gap: 16, borderTop: "1px solid var(--color-stone-200)",
        background: "#fff" }}>
        <button onClick={() => {
            if (recording) setTurns(t => [...t, { who: "me", text: "我们用了 IVF_PQ 索引，按用户和会话哈希分片..." }]);
            setRecording(r => !r);
          }}
          className={recording ? "pulse-ring" : ""}
          style={{ width: 64, height: 64, borderRadius: 999, border: "none",
            background: "var(--color-primary-500)", color: "#fff", cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "var(--shadow-primary-glow)", position: "relative", zIndex: 1 }}>
          <span style={{ position: "relative", zIndex: 2 }}>{I.mic}</span>
        </button>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: "var(--color-stone-800)" }}>
            {recording ? "点击结束回答" : "点击开始回答"}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-stone-500)", marginTop: 2 }}>
            暂未支持自动打断检测，请手动控制
          </div>
        </div>
      </footer>
    </div>
  );
}

/* ============ LIBRARY ============ */
function Library() {
  const libInput = useRef(null);
  const [files, setFiles] = useState([
    { id: 1, name: "Resume_2026_v3.pdf",  type: "PDF",  size: "284 KB", date: "5/02" },
    { id: 2, name: "ByteDance_BackendJD.txt", type: "TXT", size: "6 KB",  date: "5/02" },
    { id: 3, name: "Tencent_AlgoJD.md",   type: "MD",   size: "8 KB",  date: "4/28" },
    { id: 4, name: "Self_Intro_Draft.docx", type: "DOC", size: "42 KB", date: "4/20" },
    { id: 5, name: "System_Design_Notes.pdf", type: "PDF", size: "1.2 MB", date: "4/15" },
  ]);
  return (
    <div data-screen-label="04 Library" style={{ flex: 1, padding: "32px 40px", overflowY: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 22 }}>
        <div>
          <div className="eyebrow">个人资料库</div>
          <h2 style={{ margin: "6px 0 0" }}>我的文件</h2>
        </div>
        <input ref={libInput} type="file" multiple style={{display:"none"}}
          onChange={e => {
            const adds = [...(e.target.files || [])].map((f, i) => ({
              id: Date.now() + i, name: f.name,
              type: (f.name.split(".").pop() || "").toUpperCase().slice(0, 4),
              size: f.size > 1024 * 1024 ? (f.size / 1024 / 1024).toFixed(1) + " MB" : Math.round(f.size / 1024) + " KB",
              date: "今天",
            }));
            setFiles(p => [...adds, ...p]);
          }}/>
        <Btn icon={I.upload} onClick={() => libInput.current?.click()}>上传文件</Btn>
      </div>
      <div style={{ background: "#fff", borderRadius: 16, border: "1px solid var(--color-stone-200)",
        overflow: "hidden", boxShadow: "var(--shadow-sm)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 100px 120px 120px 80px",
          padding: "12px 20px", background: "var(--color-stone-50)",
          borderBottom: "1px solid var(--color-stone-200)", fontSize: 11, fontWeight: 600,
          color: "var(--color-stone-500)", letterSpacing: 0.04, textTransform: "uppercase" }}>
          <span>名称</span><span>类型</span><span>大小</span><span>修改时间</span><span></span>
        </div>
        {files.map(f => (
          <div key={f.id} style={{ display: "grid", gridTemplateColumns: "1fr 100px 120px 120px 80px",
            padding: "14px 20px", alignItems: "center", borderBottom: "1px solid var(--color-stone-100)",
            fontSize: 13, color: "var(--color-stone-800)" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ color: "var(--color-primary-500)" }}>{I.file}</span>
              {f.name}
            </span>
            <Pill tone="sand">{f.type}</Pill>
            <span style={{ color: "var(--color-stone-500)", fontFamily: "var(--font-mono)", fontSize: 12 }}>{f.size}</span>
            <span style={{ color: "var(--color-stone-500)", fontFamily: "var(--font-mono)", fontSize: 12 }}>{f.date}</span>
            <span style={{ display: "flex", gap: 4, justifyContent: "flex-end" }}>
              <button title="重命名" style={iconBtn()}>{I.pencil}</button>
              <button title="删除" style={iconBtn()} onClick={() => setFiles(p => p.filter(x => x.id !== f.id))}>{I.trash}</button>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
const iconBtn = () => ({ width: 28, height: 28, borderRadius: 8, border: "none",
  background: "transparent", color: "var(--color-stone-500)", cursor: "pointer",
  display: "inline-flex", alignItems: "center", justifyContent: "center" });

/* ============ MODELS ============ */
function Models() {
  const vendors = [
    { name: "DeepSeek", brand: "#5B6BC5", models: ["V4 Flash", "V4 Pro", "Reasoner"], keySet: true },
    { name: "OpenAI",   brand: "#10A37F", models: ["GPT-4o", "GPT-4o-mini", "o3"], keySet: true },
    { name: "Anthropic", brand: "#C26A4A", models: ["Claude Sonnet 4.5", "Claude Haiku 4.5", "Claude Opus 4"], keySet: false },
    { name: "Qwen (DashScope)", brand: "#8453E0", models: ["Qwen3-Max", "Qwen3-Plus", "Qwen-VL-Plus"], keySet: true },
    { name: "Moonshot", brand: "#3D6FF0", models: ["Kimi K2", "Kimi K1.5"], keySet: false },
    { name: "Zhipu",    brand: "#1971C2", models: ["GLM-4.5", "GLM-4-Plus", "GLM-4-Air"], keySet: false },
  ];
  return (
    <div data-screen-label="05 Models" style={{ flex: 1, padding: "32px 40px", overflowY: "auto" }}>
      <div className="eyebrow">模型选择</div>
      <h2 style={{ margin: "6px 0 0" }}>选择模型与配置</h2>
      <p style={{ color: "var(--color-stone-500)", marginTop: 6, marginBottom: 24 }}>
        所有调用走你自己的 API Key。配置在本地浏览器，密钥不上送服务器。
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 }}>
        {vendors.map(v => <VendorCard key={v.name} v={v}/>)}
      </div>
    </div>
  );
}
function VendorCard({ v }) {
  const [picked, setPicked] = useState(v.models[0]);
  return (
    <div style={{ background: "#fff", borderRadius: 16, padding: 20,
      border: "1px solid var(--color-stone-200)", boxShadow: "var(--shadow-sm)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: v.brand,
            color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 12, fontWeight: 600 }}>{v.name[0]}</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-stone-800)" }}>{v.name}</div>
        </div>
        <Pill tone={v.keySet ? "success" : "warn"}>{v.keySet ? "已配置" : "未配置"}</Pill>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
        {v.models.map(m => (
          <label key={m} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
            borderRadius: 10, cursor: "pointer", background: m === picked ? "var(--color-primary-50)" : "transparent",
            border: "1px solid " + (m === picked ? "var(--color-primary-200)" : "transparent") }}>
            <input type="radio" checked={m === picked} onChange={() => setPicked(m)}
              style={{ accentColor: "var(--color-primary-500)" }}/>
            <span style={{ fontSize: 13, fontFamily: "var(--font-mono)",
              color: m === picked ? "var(--color-primary-700)" : "var(--color-stone-700)" }}>{m}</span>
          </label>
        ))}
      </div>
      <Field label="API Key" type="password" icon={I.lock} value={v.keySet ? "sk-•••••••••••••••" : ""} placeholder="sk-..." onChange={() => {}}/>
    </div>
  );
}

/* ============ ME ============ */
function Me({ onLogout }) {
  return (
    <div data-screen-label="06 Me" style={{ flex: 1, padding: "32px 40px", overflowY: "auto" }}>
      <div className="eyebrow">个人中心</div>
      <h2 style={{ margin: "6px 0 22px" }}>账户</h2>
      <div style={{ maxWidth: 520, background: "#fff", borderRadius: 16, padding: 24,
        border: "1px solid var(--color-stone-200)", boxShadow: "var(--shadow-sm)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 22 }}>
          <div style={{ width: 56, height: 56, borderRadius: 999, background: "var(--color-primary-100)",
            color: "var(--color-primary-700)", display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 20, fontWeight: 600 }}>U</div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: "var(--color-stone-800)" }}>user@example.com</div>
            <div style={{ fontSize: 12, color: "var(--color-stone-500)", marginTop: 2 }}>注册于 2026/04 · Free 计划</div>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 13 }}>
          {[
            ["完成面试复盘", "12"],
            ["完成模拟面试", "3"],
            ["资料库文件",   "5"],
          ].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between",
              padding: "10px 12px", borderRadius: 10, background: "var(--color-stone-50)" }}>
              <span style={{ color: "var(--color-stone-600)" }}>{k}</span>
              <span style={{ color: "var(--color-stone-800)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>{v}</span>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 22, display: "flex", gap: 10 }}>
          <Btn kind="outline">修改密码</Btn>
          <Btn kind="danger" icon={I.logout} onClick={onLogout}>退出登录</Btn>
        </div>
      </div>
      <p style={{ marginTop: 18, fontSize: 12, color: "var(--color-stone-400)" }}>
        · 个人中心后续内容待用户研究后补充 ·
      </p>
    </div>
  );
}

function ReportQATabs({ qa, setQA }) {
  const [tab, setTab] = useState("report");
  const tabs = [{ k: "report", l: "分析报告" }, { k: "qa", l: "QA 对" }];
  return (
    <div>
      <div style={{ display: "inline-flex", padding: 4, background: "rgba(255,255,255,0.62)",
        backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)",
        border: "1px solid var(--color-stone-200)", borderRadius: 999,
        boxShadow: "var(--shadow-sm)", marginBottom: 22, position: "relative" }}>
        <div style={{ position:"absolute", top:4, bottom:4, width:"calc(50% - 4px)",
          left: tab==="report" ? 4 : "calc(50% + 0px)",
          background:"#fff", borderRadius:999, boxShadow:"var(--shadow-sm)",
          transition:"left 280ms var(--ease-soft)" }}></div>
        {tabs.map(t => (
          <button key={t.k} onClick={()=>setTab(t.k)}
            style={{ position:"relative", zIndex:1, padding:"7px 22px", border:"none",
              background:"transparent", cursor:"pointer", fontSize: 13, fontWeight: 500,
              color: tab===t.k ? "var(--color-primary-700)" : "var(--color-stone-600)",
              fontFamily:"var(--font-sans)" }}>{t.l}</button>
        ))}
      </div>
      {tab === "report" ? <Report/> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {qa.map((p, i) => <QAItem key={i} idx={i} item={p} onChange={patch => setQA(i, patch)}/>)}
        </div>
      )}
    </div>
  );
}

function Report() {
  const dims = [
    { k:"专业深度", v: 78, tone:"#C26A4A" },
    { k:"表达逻辑", v: 85, tone:"#7AA37A" },
    { k:"项目掌控", v: 72, tone:"#D9A24A" },
    { k:"问题理解", v: 88, tone:"#7A93C9" },
    { k:"沟通节奏", v: 65, tone:"#B98AC0" },
  ];
  const overall = Math.round(dims.reduce((s, d) => s + d.v, 0) / dims.length);
  return (
    <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display:"grid", gridTemplateColumns:"180px 1fr", gap: 16,
        background:"#fff", borderRadius: 16, padding: 22,
        border:"1px solid var(--color-stone-200)", boxShadow:"var(--shadow-sm)" }}>
        <div style={{ display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center",
          background:"var(--color-cream-50)", borderRadius: 14, padding: 16 }}>
          <div style={{ fontSize: 11, color:"var(--color-stone-500)", letterSpacing: 0.06, textTransform:"uppercase" }}>综合评分</div>
          <div style={{ fontSize: 44, fontWeight: 700, color:"var(--color-primary-600)",
            lineHeight: 1.1, marginTop: 6, fontFamily:"var(--font-display)" }}>{overall}</div>
          <div style={{ fontSize: 11, color:"var(--color-stone-500)", marginTop: 4 }}>/ 100 · B+</div>
        </div>
        <div style={{ display:"flex", flexDirection:"column", gap: 10, justifyContent:"center" }}>
          {dims.map(d => (
            <div key={d.k} style={{ display:"grid", gridTemplateColumns:"80px 1fr 36px",
              alignItems:"center", gap: 10 }}>
              <span style={{ fontSize: 12, color:"var(--color-stone-700)" }}>{d.k}</span>
              <div style={{ height: 6, background:"var(--color-stone-100)", borderRadius: 999, overflow:"hidden" }}>
                <div style={{ width: d.v+"%", height:"100%", background: d.tone, borderRadius: 999,
                  transition:"width 600ms var(--ease-soft)" }}></div>
              </div>
              <span style={{ fontSize: 12, fontFamily:"var(--font-mono)", color:"var(--color-stone-600)",
                textAlign:"right" }}>{d.v}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap: 14 }}>
        <ReportList tone="success" title="亮点" items={[
          "技术选型部分能引用真实数据，体现对量化指标的关注",
          "对 Whisper 流式分段的工程优化思路完整",
          "整体表达节奏自然，回答之间衔接顺畅",
        ]}/>
        <ReportList tone="warn" title="需要加强" items={[
          "Milvus 选型对比缺乏 P95 等量化口径",
          "系统设计未给出降级 / 限流方案",
          "项目难点的'我做了什么'比例偏低，更多在描述方案",
        ]}/>
      </div>

      <article style={{ background:"#fff", borderRadius: 16, padding: 22,
        border:"1px solid var(--color-stone-200)", boxShadow:"var(--shadow-sm)" }}>
        <div className="eyebrow" style={{ marginBottom: 10 }}>中长篇面试报告</div>
        <div style={{ fontSize: 14, lineHeight: 1.75, color:"var(--color-stone-700)" }}>
          <p>本次面试整体呈现出 <b>"技术广度高、深度不均"</b> 的特征。候选人在介绍 Interview Copilot 项目时，能够清晰交代后端、前端、RAG、ASR 四个子系统的边界，并指出团队对类型安全和上手成本的关注，这是面试官评估 mid-level 工程师非常关注的"系统化思考"信号。</p>
          <p>但在涉及 <b>向量库选型</b> 与 <b>系统设计</b> 的纵深问题上，回答的颗粒度明显下降。例如关于 Milvus vs pgvector，候选人提到了"召回耗时上升"，但没有给出实测 P95、写入吞吐或运维成本这些可对比指标，使得选型理由更像偏好而非工程权衡。系统设计部分缺失降级、限流和兜底，是 SDE-II 面试评估的常见扣分项。</p>
          <p>建议接下来的两周以 <b>"指标化表达"</b> 为训练目标：把每个项目里的选型、性能、规模拆分成 3 个量化条目；并在每次回答末尾补一句"如果重来会怎么改"，让面试官看到你的复盘能力。</p>
        </div>
      </article>
    </div>
  );
}

function ReportList({ tone, title, items }) {
  const map = {
    success: { bg:"var(--color-success-50)", c:"var(--color-success-700)", dot:"var(--color-success-500)" },
    warn:    { bg:"var(--color-warning-50)", c:"var(--color-warning-700)", dot:"var(--color-warning-500)" },
  }[tone];
  return (
    <div style={{ background:"#fff", borderRadius: 16, padding: 20,
      border:"1px solid var(--color-stone-200)", boxShadow:"var(--shadow-sm)" }}>
      <div style={{ display:"flex", alignItems:"center", gap: 8, marginBottom: 12 }}>
        <span style={{ width: 22, height: 22, borderRadius: 6, background: map.bg, color: map.c,
          display:"inline-flex", alignItems:"center", justifyContent:"center", fontSize: 12 }}>{tone==="success"?"✓":"!"}</span>
        <span style={{ fontSize: 14, fontWeight: 600, color:"var(--color-stone-800)" }}>{title}</span>
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle:"none", display:"flex", flexDirection:"column", gap: 8 }}>
        {items.map((t, i) => (
          <li key={i} style={{ display:"flex", gap: 8, fontSize: 13, lineHeight: 1.55, color:"var(--color-stone-700)" }}>
            <span style={{ width: 6, height: 6, borderRadius: 999, background: map.dot,
              marginTop: 7, flexShrink: 0 }}></span>
            <span>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ============ ABILITY ANALYSIS ============ */
function Ability() {
  const axes = [
    { k: "技术深度",   v: 72 },
    { k: "系统设计",   v: 58 },
    { k: "表达逻辑",   v: 85 },
    { k: "项目掌控",   v: 76 },
    { k: "问题理解",   v: 88 },
    { k: "沟通节奏",   v: 64 },
  ];
  const N = axes.length, R = 110, CX = 160, CY = 160;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / N;
    return [CX + Math.cos(a) * r, CY + Math.sin(a) * r];
  };
  const grid = [0.25, 0.5, 0.75, 1].map(f =>
    axes.map((_, i) => pt(i, R * f).join(",")).join(" ")
  );
  const polyPts = axes.map((d, i) => pt(i, R * (d.v / 100)).join(",")).join(" ");
  const overall = Math.round(axes.reduce((s, a) => s + a.v, 0) / axes.length);
  const weaknesses = [
    { k: "系统设计", v: 58, why: "近 12 次面试中，被问到限流 / 缓存 / 降级时的回答完整度只有 42%。",
      docs: [
        { t: "DDIA 12-13 章 · 一致性与共识", url: "https://dataintensive.net/" },
        { t: "字节后端 · 高并发系统设计模板",  url: "https://github.com/donnemartin/system-design-primer" },
      ],
      practice: [
        { t: "每天 1 道 system-design 题 × 14 天", url: "https://github.com/donnemartin/system-design-primer#system-design-interview-questions-with-solutions" },
        { t: "录音回答并对照官方解法复盘",        url: "/library?tag=system-design" },
      ] },
    { k: "沟通节奏", v: 64, why: "回答平均长度 1 分 40 秒，但前 20 秒内常未给出结论。",
      docs: [
        { t: "《结构化表达》第 3 章 · 金字塔原理", url: "https://en.wikipedia.org/wiki/Minto_pyramid_principle" },
      ],
      practice: [
        { t: "所有回答先用一句话给结论，再展开 3 条要点", url: "/mock?focus=structure" },
      ] },
    { k: "技术深度", v: 72, why: "RAG / 向量库选型问题，量化指标提及率偏低。",
      docs: [
        { t: "Milvus 官方文档 · 索引选型矩阵", url: "https://milvus.io/docs/index.md" },
        { t: "Pinecone Benchmark 2025",       url: "https://www.pinecone.io/learn/" },
      ],
      practice: [
        { t: "每个项目准备 3 条量化指标（QPS / P95 / 成本）", url: "/mock?focus=metrics" },
      ] },
  ];
  return (
    <div data-screen-label="07 Ability" style={{ flex: 1, overflowY: "auto", background: "var(--color-stone-50)" }}>
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "32px 36px" }}>
        <div className="eyebrow">能力分析</div>
        <h2 style={{ margin: "6px 0 4px" }}>个人能力雷达</h2>
        <p style={{ color: "var(--color-stone-500)", marginTop: 0, marginBottom: 24 }}>
          基于你最近 12 次面试 ( 复盘 + 模拟 ) 的综合表现，每周自动更新。
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: 20, marginBottom: 20 }}>
          <div style={{ background: "#fff", borderRadius: 16, padding: 22,
            border: "1px solid var(--color-stone-200)", boxShadow: "var(--shadow-sm)",
            display: "flex", flexDirection: "column", alignItems: "center" }}>
            <svg width="320" height="320" viewBox="0 0 320 320">
              {grid.map((g, i) => (
                <polygon key={i} points={g} fill="none"
                  stroke="var(--color-stone-200)" strokeWidth="1"
                  strokeDasharray={i === 3 ? "" : "2 3"}/>
              ))}
              {axes.map((d, i) => {
                const [x, y] = pt(i, R);
                return <line key={i} x1={CX} y1={CY} x2={x} y2={y}
                  stroke="var(--color-stone-200)" strokeWidth="1"/>;
              })}
              <polygon points={polyPts} fill="var(--color-primary-300)" fillOpacity="0.32"
                stroke="var(--color-primary-500)" strokeWidth="2"/>
              {axes.map((d, i) => {
                const [x, y] = pt(i, R * (d.v / 100));
                return <circle key={i} cx={x} cy={y} r="4" fill="var(--color-primary-600)"/>;
              })}
              {axes.map((d, i) => {
                const [x, y] = pt(i, R + 24);
                return (
                  <text key={i} x={x} y={y} fontSize="11"
                    fontFamily="var(--font-sans)" fill="var(--color-stone-700)"
                    textAnchor="middle" dominantBaseline="middle">{d.k}</text>
                );
              })}
            </svg>
            <div style={{ marginTop: 6, textAlign: "center" }}>
              <div style={{ fontSize: 11, color: "var(--color-stone-500)", letterSpacing: 0.06, textTransform: "uppercase" }}>综合能力</div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "var(--color-primary-600)",
                fontFamily: "var(--font-display)", lineHeight: 1.1, marginTop: 2 }}>{overall}<span style={{ fontSize: 14, color: "var(--color-stone-500)", marginLeft: 4 }}>/ 100</span></div>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ background: "#fff", borderRadius: 16, padding: 22,
              border: "1px solid var(--color-stone-200)", boxShadow: "var(--shadow-sm)" }}>
              <div className="eyebrow" style={{ marginBottom: 14 }}>各维度趋势 · 近 4 周</div>
              <div style={{ display: "grid", gridTemplateColumns: "100px 1fr 40px", rowGap: 12, columnGap: 12, alignItems: "center" }}>
                {axes.map(a => (
                  <React.Fragment key={a.k}>
                    <span style={{ fontSize: 13, color: "var(--color-stone-700)" }}>{a.k}</span>
                    <div style={{ height: 8, background: "var(--color-stone-100)", borderRadius: 999, overflow: "hidden" }}>
                      <div style={{ width: a.v + "%", height: "100%",
                        background: a.v < 65 ? "var(--color-warning-500)" : a.v < 80 ? "var(--color-primary-400)" : "var(--color-success-500)",
                        borderRadius: 999, transition: "width 600ms var(--ease-soft)" }}></div>
                    </div>
                    <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--color-stone-600)", textAlign: "right" }}>{a.v}</span>
                  </React.Fragment>
                ))}
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
              {[
                { l: "已完成面试", v: 12, sub: "+3 本周" },
                { l: "平均时长",   v: "38m", sub: "−4m vs 上周" },
                { l: "最强维度",   v: "问题理解", sub: "88 / 100" },
              ].map(s => (
                <div key={s.l} style={{ background: "#fff", borderRadius: 14, padding: 16,
                  border: "1px solid var(--color-stone-200)", boxShadow: "var(--shadow-sm)" }}>
                  <div style={{ fontSize: 11, color: "var(--color-stone-500)", letterSpacing: 0.04, textTransform: "uppercase" }}>{s.l}</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: "var(--color-stone-800)", marginTop: 4,
                    fontFamily: "var(--font-display)" }}>{s.v}</div>
                  <div style={{ fontSize: 11, color: "var(--color-stone-500)", marginTop: 2 }}>{s.sub}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 4, height: 16, borderRadius: 2, background: "var(--color-warning-500)" }}></span>
          <h3 style={{ margin: 0 }}>需要改善的薄弱点</h3>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {weaknesses.map(w => (
            <div key={w.k} style={{ background: "#fff", borderRadius: 16, padding: 22,
              border: "1px solid var(--color-stone-200)", boxShadow: "var(--shadow-sm)",
              display: "grid", gridTemplateColumns: "160px 1fr", gap: 22 }}>
              <div style={{ display: "flex", flexDirection: "column", justifyContent: "center",
                background: "var(--color-warning-50)", borderRadius: 12, padding: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-stone-800)" }}>{w.k}</div>
                <div style={{ fontSize: 30, fontWeight: 700, color: "var(--color-warning-700)",
                  fontFamily: "var(--font-display)", marginTop: 4 }}>{w.v}</div>
                <div style={{ fontSize: 11, color: "var(--color-stone-500)", marginTop: 2 }}>当前得分</div>
              </div>
              <div>
                <p style={{ margin: "0 0 14px", fontSize: 13, lineHeight: 1.6, color: "var(--color-stone-700)" }}>{w.why}</p>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                  <div>
                    <div className="eyebrow" style={{ marginBottom: 8 }}>推荐文档</div>
                    <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                      {w.docs.map(d => (
                        <li key={d.t} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                          <span style={{ color: "var(--color-primary-500)", flexShrink: 0 }}>{I.book}</span>
                          <a href={d.url} target="_blank" rel="noreferrer"
                            style={{ color: "var(--color-stone-700)", textDecoration: "none",
                              borderBottom: "1px solid var(--color-stone-200)", paddingBottom: 1,
                              transition: "color 120ms, border-color 120ms" }}
                            onMouseEnter={e => { e.currentTarget.style.color = "var(--color-primary-700)"; e.currentTarget.style.borderBottomColor = "var(--color-primary-300)"; }}
                            onMouseLeave={e => { e.currentTarget.style.color = "var(--color-stone-700)"; e.currentTarget.style.borderBottomColor = "var(--color-stone-200)"; }}>
                            {d.t}<span style={{ marginLeft: 4, opacity: 0.55, fontSize: 11 }}>↗</span>
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="eyebrow" style={{ marginBottom: 8 }}>练习计划</div>
                    <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                      {w.practice.map(p => (
                        <li key={p.t} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                          <span style={{ color: "var(--color-success-600)", flexShrink: 0 }}>{I.check}</span>
                          <a href={p.url}
                            style={{ color: "var(--color-stone-700)", textDecoration: "none",
                              borderBottom: "1px solid var(--color-stone-200)", paddingBottom: 1,
                              transition: "color 120ms, border-color 120ms" }}
                            onMouseEnter={e => { e.currentTarget.style.color = "var(--color-success-700)"; e.currentTarget.style.borderBottomColor = "var(--color-success-500)"; }}
                            onMouseLeave={e => { e.currentTarget.style.color = "var(--color-stone-700)"; e.currentTarget.style.borderBottomColor = "var(--color-stone-200)"; }}>
                            {p.t}<span style={{ marginLeft: 4, opacity: 0.55, fontSize: 11 }}>→</span>
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
                  <Btn size="sm" kind="outline" icon={I.book}>开始学习</Btn>
                  <Btn size="sm" kind="outline" icon={I.mic}>针对性模拟</Btn>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

window.Screens = { Auth, Review, Mock, Ability, Library, Models, Me };
