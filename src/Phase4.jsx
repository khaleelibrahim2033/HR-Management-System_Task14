import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw, CheckCircle2, MessageSquare, ClipboardList, Megaphone, UserRound, LogOut } from "lucide-react";
import { request, downloadFile } from "./api";

const label = (v) => String(v ?? "").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
const isHR = user => user.role !== "EMPLOYEE";
const today = new Date().toISOString().slice(0,10);

export default function Phase4({ page, user, refreshKey, flash, onError }) {
  const [rows, setRows] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [profile, setProfile] = useState(null);
  const [preferences, setPreferences] = useState({email_enabled:false, announcements_enabled:true, task_reminders_enabled:true});
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const paths = { onboarding:"/onboarding", resignations:"/resignations", announcements:"/announcements", tasks:"/tasks", feedback:"/feedback" };
      if (page === "profile-settings") {
        const p = await request("/profile/settings"); setProfile(p);
        setPreferences(p.preferences || preferences); return;
      }
      if (page === "integrations") { setRows([]); return; }
      setRows(await request(paths[page] || "/announcements"));
      if (isHR(user) && ["onboarding","tasks"].includes(page)) setEmployees(await request("/employees"));
    } catch (e) { onError(e.message); }
  }, [page, user, refreshKey]);
  useEffect(() => { load(); }, [load]);

  const submit = async (event) => {
    event.preventDefault(); setBusy(true);
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      if (page === "onboarding") await request("/onboarding", {method:"POST", body:JSON.stringify({...values, employee_id:Number(values.employee_id)})});
      if (page === "announcements") await request("/announcements", {method:"POST", body:JSON.stringify(values)});
      if (page === "tasks") await request("/tasks", {method:"POST", body:JSON.stringify({...values, assigned_to:Number(values.assigned_to)})});
      if (page === "resignations") await request("/resignations", {method:"POST", body:JSON.stringify({...values, notice_period:Number(values.notice_period)})});
      if (page === "feedback") await request("/feedback", {method:"POST", body:JSON.stringify({...values, rating:Number(values.rating)})});
      event.currentTarget.reset(); flash("Saved successfully."); load();
    } catch(e) { onError(e.message); } finally { setBusy(false); }
  };
  const changeStatus = async (resource, item, status) => {
    try { await request(`/${resource}/${item.id}`, {method:"PATCH", body:JSON.stringify({status})}); flash("Status updated."); load(); }
    catch(e) { onError(e.message); }
  };
  const exportData = async (resource, format="csv") => {
    try { await downloadFile(`/integrations/export/${resource}?format=${format}`, `worksphere-${resource}.${format}`); }
    catch(e) { onError(e.message); }
  };
  const saveProfile = async e => {
    e.preventDefault(); const values=Object.fromEntries(new FormData(e.currentTarget).entries());
    try { await request("/profile/settings",{method:"PATCH",body:JSON.stringify(values)}); flash("Profile updated."); load(); } catch(err){onError(err.message);}
  };
  const savePrefs = async e => {
    e.preventDefault();
    try { await request("/profile/preferences",{method:"PUT",body:JSON.stringify(preferences)}); flash("Preferences saved."); } catch(err){onError(err.message);}
  };
  const changePassword = async e => {
    e.preventDefault(); const values=Object.fromEntries(new FormData(e.currentTarget).entries());
    try { await request("/profile/change-password",{method:"POST",body:JSON.stringify(values)}); e.currentTarget.reset(); flash("Password changed."); } catch(err){onError(err.message);}
  };
  const heading = {onboarding:"Employee onboarding", resignations:"Resignation & exit management", announcements:"Internal announcements", tasks:"Task assignment & tracking", integrations:"Third-party integrations", feedback:"Employee feedback", "profile-settings":"Profile & settings"}[page];
  const descriptions = {onboarding:"Assign onboarding checklist items and track completion.",resignations:"Submit resignations and review exit workflow status.",announcements:"Share important updates with the whole organization.",tasks:"Assign work and track employee task completion.",integrations:"Export reports and connect calendar/email services.",feedback:"Collect employee feedback and review ratings.","profile-settings":"Manage your account details, password, and notification preferences."};
  return <div className="stack-layout">
    <section className="panel"><div className="panel-title"><div><h3>{heading}</h3><p>{descriptions[page]}</p></div><button className="button button-quiet" onClick={load}><RefreshCw size={15}/> Refresh</button></div>
      {page==="onboarding" && isHR(user) && <form className="inline-form" onSubmit={submit}>
        <label className="field">Employee<select name="employee_id" required defaultValue=""><option value="" disabled>Select employee</option>{employees.map(e=><option key={e.id} value={e.id}>{e.full_name} · {e.department}</option>)}</select></label>
        <label className="field">Task name<input name="task_name" required minLength="2" placeholder="Complete induction"/></label>
        <label className="field">Due date<input name="due_date" type="date" min={today} required/></label><button className="button button-primary" disabled={busy}>Assign task</button>
      </form>}
      {page==="announcements" && isHR(user) && <form className="stack-layout" onSubmit={submit}><label className="field">Title<input name="title" required minLength="2" maxLength="180" placeholder="Company update"/></label><label className="field">Message<textarea name="message" required minLength="2" rows="3" placeholder="Write announcement..."/></label><button className="button button-primary" disabled={busy}>Publish announcement</button></form>}
      {page==="tasks" && isHR(user) && <form className="inline-form" onSubmit={submit}><label className="field">Assign employee<select name="assigned_to" required defaultValue=""><option value="" disabled>Select employee</option>{employees.map(e=><option key={e.id} value={e.id}>{e.full_name}</option>)}</select></label><label className="field">Title<input name="title" required minLength="2"/></label><label className="field">Due date<input name="due_date" type="date" required/></label><label className="field">Description<input name="description" maxLength="10000"/></label><button className="button button-primary" disabled={busy}>Assign task</button></form>}
      {page==="resignations" && <form className="stack-layout" onSubmit={submit}><label className="field">Reason<textarea name="reason" required minLength="5" rows="3" placeholder="Please explain your reason"/></label><label className="field">Notice period (days)<input name="notice_period" type="number" min="0" max="365" defaultValue="30" required/></label><button className="button button-primary" disabled={busy}>Submit resignation</button></form>}
      {page==="feedback" && <form className="stack-layout" onSubmit={submit}><label className="field">Your feedback<textarea name="message" required minLength="3" rows="3" placeholder="Share your experience"/></label><label className="field">Rating<select name="rating" defaultValue="5">{[5,4,3,2,1].map(n=><option key={n} value={n}>{n} / 5</option>)}</select></label><button className="button button-primary" disabled={busy}>Submit feedback</button></form>}
    </section>
    {page==="profile-settings" && profile && <><section className="panel"><h3>Account details</h3><form className="inline-form" onSubmit={saveProfile}><label className="field">Username<input value={profile.user.username} disabled readOnly/></label><label className="field">Email<input type="email" name="email" defaultValue={profile.user.email} required/></label><label className="field">Role<input value={profile.user.role} disabled readOnly/></label><button className="button button-primary">Save profile</button></form>{profile.employee && <p>{profile.employee.full_name} · {profile.employee.designation} · {profile.employee.department}</p>}</section>
    <section className="panel"><h3>Change password</h3><form className="inline-form" onSubmit={changePassword}><label className="field">Current password<input name="current_password" type="password" required/></label><label className="field">New password<input name="new_password" type="password" minLength="8" required/></label><button className="button button-primary">Change password</button></form></section>
    <section className="panel"><h3>Notification preferences</h3><form className="stack-layout" onSubmit={savePrefs}>{Object.entries({email_enabled:"Email notifications",announcements_enabled:"Announcement notifications",task_reminders_enabled:"Task reminders"}).map(([key,text])=><label key={key} className="field"><span><input type="checkbox" checked={!!preferences[key]} onChange={e=>setPreferences(p=>({...p,[key]:e.target.checked}))}/> {text}</span></label>)}<button className="button button-primary">Save preferences</button></form></section></>}
    {page==="integrations" && <section className="panel"><h3>Export reports</h3><p>Download supported HR records as CSV files for reporting and audit workflows.</p><div className="phase-card-grid">{["onboarding","resignations","announcements","tasks","employees","attendance","leaves","payroll","feedback"].filter(r=>isHR(user)||!["employees","attendance","leaves","payroll","feedback"].includes(r)).map(r=><div className="phase-info-card" key={r}><span className="phase-icon"><Download size={17}/></span><strong>{label(r)}</strong><div className="inline-form"><button className="button button-quiet" onClick={()=>exportData(r,"csv")}>CSV</button><button className="button button-quiet" onClick={()=>exportData(r,"pdf")}>PDF</button></div></div>)}</div><hr/><h3>Calendar integration</h3><p>Export approved leave to a calendar-compatible .ics file and import it into Google Calendar, Outlook, or Apple Calendar.</p><button className="button button-primary" onClick={()=>exportData("calendar","ics")}>Export leave calendar (.ics)</button><hr/><h3>Email integration</h3><p>HR/Admin can send a configuration test after setting SMTP_HOST, SMTP_PORT, SMTP_FROM, and SMTP_PASSWORD in the backend environment.</p><form className="inline-form" onSubmit={async e=>{e.preventDefault();try{const email=new FormData(e.currentTarget).get("to_email");const result=await request(`/integrations/email-test?to_email=${encodeURIComponent(email)}`,{method:"POST"});flash(result.message);}catch(err){onError(err.message);}}}><label className="field">Test recipient email<input type="email" name="to_email" required/></label><button className="button button-primary" disabled={!isHR(user)}>Send test email</button></form></section>}
    {page==="announcements" && <section className="panel"><div className="panel-title"><div><h3>Announcement board</h3><p>Latest organization updates</p></div><Megaphone size={18}/></div>{rows.length?rows.map(x=><article className="phase-info-card" key={x.id}><strong>{x.title}</strong><p>{x.message}</p><small>{x.created_at?.slice(0,10)}</small></article>):<p className="empty-note">No announcements yet.</p>}</section>}
    {page==="onboarding" && <section className="panel"><div className="panel-title"><div><h3>Onboarding checklist</h3><p>{rows.filter(x=>x.status==="COMPLETED").length} of {rows.length} tasks completed</p></div><ClipboardList size={18}/></div>{rows.length?rows.map(x=><div className="phase-info-card" key={x.id}><strong>{x.task_name}</strong><span>Due {x.due_date} · Employee #{x.employee_id}</span><span>{label(x.status)}</span>{x.status==="PENDING"&&<button className="button button-quiet" onClick={()=>changeStatus("onboarding",x,"COMPLETED")}>Mark completed</button>}</div>):<p className="empty-note">No onboarding tasks found.</p>}</section>}
    {["tasks","resignations","feedback"].includes(page) && <section className="panel"><h3>{page==="tasks"?"Task list":page==="resignations"?"Exit status":"Feedback dashboard"}</h3>{rows.length?rows.map(x=><div className="phase-info-card" key={x.id}><strong>{x.title||x.reason||`Feedback #${x.id}`}</strong><p>{x.description||x.message||""}</p><span>{x.due_date?`Due ${x.due_date} · `:""}{x.status?label(x.status):`Rating: ${x.rating}/5`}</span>{page==="tasks"&&x.status==="PENDING"&&<button className="button button-quiet" onClick={()=>changeStatus("tasks",x,"COMPLETED")}>Mark completed</button>}{page==="resignations"&&isHR(user)&&x.status==="PENDING"&&<div className="inline-form"><button className="button button-primary" onClick={()=>changeStatus("resignations",x,"APPROVED")}>Approve</button><button className="button button-quiet" onClick={()=>changeStatus("resignations",x,"REJECTED")}>Reject</button></div>}</div>):<p className="empty-note">No records found.</p>}</section>}
  </div>;
}
