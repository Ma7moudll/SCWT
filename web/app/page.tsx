'use client'

import { useState } from 'react'
import {
  ArrowLeft, Bell, CalendarDays, Check, ChevronRight, CircleHelp, ClipboardList,
  Gift, Leaf, LogOut, MapPin, Medal, PackageCheck, QrCode, Recycle, ScanLine,
  Settings, Sparkles, Trophy, UserRound, WalletCards, Waves, Zap
} from 'lucide-react'

type Screen = 'home' | 'schedule' | 'scan' | 'rewards' | 'impact' | 'profile' | 'history' | 'badges'
type AuthScreen = 'login' | 'signup'

const navItems: { id: Screen; label: string; icon: typeof Leaf }[] = [
  { id: 'home', label: 'Home', icon: Leaf },
  { id: 'history', label: 'History', icon: ClipboardList },
  { id: 'rewards', label: 'Rewards', icon: Trophy },
  { id: 'profile', label: 'Profile', icon: UserRound },
]

const metrics = [
  { label: 'Waste Recycled', value: '12 kg', icon: Recycle, tone: 'orange' },
  { label: 'CO₂ Reduced', value: '18 kg', icon: Waves, tone: 'purple' },
  { label: 'Trees Saved', value: '2', icon: Leaf, tone: 'green' },
  { label: 'Energy Saved', value: '15 kWh', icon: Zap, tone: 'violet' },
  { label: 'Water Saved', value: '120 L', icon: Waves, tone: 'blue' },
]

function LeafMark({ small = false }: { small?: boolean }) {
  return <span className={small ? 'leaf-mark leaf-mark--small' : 'leaf-mark'}><Leaf strokeWidth={2.4} /></span>
}

function BottomNav({ screen, go }: { screen: Screen; go: (screen: Screen) => void }) {
  return <nav className="bottom-nav" aria-label="Primary navigation">
    {navItems.map(({ id, label, icon: Icon }) => <button key={id} className={screen === id ? 'nav-item active' : 'nav-item'} onClick={() => go(id)} aria-label={label}>
      <Icon /><span>{label}</span>
    </button>)}
  </nav>
}

function Header({ title, back, go }: { title?: string; back?: boolean; go: (screen: Screen) => void }) {
  return <header className="screen-header">
    {back ? <button className="icon-button" onClick={() => go('home')} aria-label="Go back"><ArrowLeft /></button> : <div />}
    {title ? <h1>{title}</h1> : <div className="header-brand"><LeafMark small /><span>SCWT</span></div>}
    <button className="icon-button" onClick={() => window.alert('Settings are coming soon.')} aria-label="Settings"><Settings /></button>
  </header>
}

function PointsCard() {
  return <div className="points-card"><div><span>Total Points</span><strong>1,250</strong><em>+120 this week</em></div><Leaf className="points-leaf" /></div>
}

function Home({ go }: { go: (screen: Screen) => void }) {
  return <div className="screen"><div className="home-top"><div><p className="eyebrow">Hi, Emma!</p><p className="subtle">Let&apos;s make a difference today</p></div><button className="notification" onClick={() => window.alert('You have no new notifications.')} aria-label="Notifications"><Bell /><i /></button></div>
    <PointsCard />
    <section><div className="section-heading"><h2>Quick Actions</h2></div><div className="quick-actions">
      {[['Recycle Now', Recycle, 'scan'], ['Schedule Pickup', CalendarDays, 'schedule'], ['Scan QR', QrCode, 'scan']].map(([label, Icon, target]) => { const ActionIcon = Icon as typeof Leaf; return <button className="quick-action" key={label as string} onClick={() => go(target as Screen)}><span><ActionIcon /></span><small>{label as string}</small></button> })}
    </div></section>
    <section><div className="section-heading"><h2>Pickup Status</h2></div><div className="pickup-status"><div><strong>Next pickup tomorrow</strong><em>10:00 AM - 12:00 PM</em></div><span className="status-icon"><CalendarDays /></span></div></section>
    <button className="impact-teaser" onClick={() => go('impact')} aria-label="View your impact"><div><span className="eyebrow">Your impact</span><strong>67 kg</strong><p>CO₂ reduced this month</p></div><LeafMark /></button>
  </div>
}

function Schedule({ go }: { go: (screen: Screen) => void }) {
  const [waste, setWaste] = useState('Plastic'); const [submitted, setSubmitted] = useState(false)
  return <div className="screen"><Header title="Schedule Pickup" back go={go} /><div className="illustration-bin"><PackageCheck /></div><p className="center-copy">Choose your waste type<br />and schedule a pickup.</p>
    <div className="choice-row">{['Plastic', 'Paper', 'Glass', 'Metal'].map(item => <button className={waste === item ? 'choice active' : 'choice'} onClick={() => setWaste(item)} key={item}>{item}</button>)}</div>
    <div className="field-stack"><label>Pickup date<select defaultValue="Tomorrow"><option>Tomorrow</option><option>Friday, Mar 8</option><option>Saturday, Mar 9</option></select></label><label>Time slot<select defaultValue="10:00 AM - 12:00 PM"><option>10:00 AM - 12:00 PM</option><option>2:00 PM - 4:00 PM</option></select></label><label>Pickup address<div className="fake-input"><MapPin /> 24 Green Street, New York</div></label></div>
    <button className="primary-button" onClick={() => setSubmitted(true)}><CalendarDays /> Schedule New Pickup</button>
    <div className="upcoming"><div className="row-between"><span>Upcoming Pickup</span><button onClick={() => go('history')}>View All</button></div><strong>Tomorrow, 10:00 AM - 12:00 PM</strong><small>{waste} recycling pickup</small></div>
    {submitted && <div className="toast"><Check /> Pickup scheduled successfully</div>}
  </div>
}

function Scan({ go }: { go: (screen: Screen) => void }) { const [scanned, setScanned] = useState(false); return <div className="screen"><Header title="Scan & Earn" back go={go} /><div className="scan-banner">Scan a QR code on<br />the recycling bin <Leaf /></div><div className="scanner-card"><div className="scanner-frame"><QrCode /></div><div className="ready"><span />{scanned ? 'Scan complete' : 'Ready to scan'}</div></div><button className="primary-button" onClick={() => setScanned(true)}><ScanLine /> {scanned ? 'Scanned Successfully' : 'Start Scanning'}</button>{scanned && <div className="success-card"><Trophy /><div><strong>Great job!</strong><p>You earned 100 points</p></div></div>}<HowItWorks go={go} /></div> }
function HowItWorks({ go }: { go: (screen: Screen) => void }) { return <section className="how"><h2>How it works?</h2><div className="steps">{[['Scan QR', QrCode, 'scan'], ['Recycle', Recycle, 'scan'], ['Earn Points', Gift, 'rewards'], ['Get Rewards', Trophy, 'rewards']].map(([label, Icon, target]) => { const StepIcon = Icon as typeof Leaf; return <button key={label as string} onClick={() => go(target as Screen)} aria-label={label as string}><span><StepIcon /></span><small>{label as string}</small></button> })}</div></section> }

function Rewards({ go }: { go: (screen: Screen) => void }) { const [redeemed, setRedeemed] = useState(false); return <div className="screen rewards-screen"><Header title="Rewards" back go={go} /><div className="reward-hero"><span><Trophy /></span><p>Your Points</p><strong>1,250</strong><small>+120 this week</small></div><div className="redeem-card"><h2>Redeem your points</h2><div className="reward-options">{[['20% Off', 'Eco Store', Gift], ['$5 Coupon', 'GreenMart', WalletCards], ['Free Pickup', 'Next Order', PackageCheck]].map(([a, b, Icon]) => { const RewardIcon = Icon as typeof Leaf; return <button key={a as string} onClick={() => setRedeemed(true)}><span><RewardIcon /></span><strong>{a as string}</strong><small>{b as string}</small></button> })}</div><button className="primary-button" onClick={() => setRedeemed(true)}>Redeem Now</button></div>{redeemed && <div className="toast"><Check /> Reward redeemed successfully</div>}</div> }

function Impact({ go }: { go: (screen: Screen) => void }) { return <div className="screen"><Header title="Your Impact" back go={go} /><select className="month-select" defaultValue="This Month"><option>This Month</option><option>Last Month</option></select><div className="metrics-list">{metrics.map(({ label, value, icon: Icon, tone }) => <div className="metric" key={label}><span className={`metric-icon ${tone}`}><Icon /></span><span>{label}</span><strong>{value}</strong></div>)}</div><div className="total-impact"><div><span>Total Impact</span><strong>67 kg</strong><small>CO₂ Reduced</small><div className="progress"><i /></div></div><LeafMark /></div><div className="impact-chart"><div className="row-between"><h2>Monthly progress</h2><span>+24%</span></div><div className="bars">{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'].map((m, i) => <div key={m}><i style={{ height: `${30 + i * 10}%` }} /><small>{m}</small></div>)}</div></div></div> }

function Profile({ go }: { go: (screen: Screen) => void }) { const items = [['Pickup History', ClipboardList, 'history'], ['My Badges', Medal, 'badges'], ['Payment Methods', WalletCards, 'notice'], ['Addresses', MapPin, 'notice'], ['Notifications', Bell, 'notice'], ['Help Center', CircleHelp, 'notice'], ['Logout', LogOut, 'home']]; return <div className="screen"><Header go={go} /><div className="profile-head"><div className="avatar">EJ</div><h1>Emma Johnson</h1><p>emma@example.com</p></div><PointsCard /><div className="profile-list">{items.map(([label, Icon, target]) => { const ProfileIcon = Icon as typeof Leaf; return <button key={label as string} onClick={() => target === 'notice' ? window.alert(`${label} is ready for your account.`) : target === 'home' && label === 'Logout' ? window.alert('You have been logged out of this demo.') : go(target as Screen)}><ProfileIcon /><span>{label as string}</span><ChevronRight /></button> })}</div></div> }

function History({ go }: { go: (screen: Screen) => void }) { const history = [['Mar 4, 2024', 'Plastic', '4.2 kg', '+80 pts'], ['Feb 26, 2024', 'Glass', '2.8 kg', '+55 pts'], ['Feb 18, 2024', 'Paper', '5.1 kg', '+110 pts']]; return <div className="screen"><Header title="Pickup History" back go={go} /><div className="history-list">{history.map(([date, type, weight, points]) => <div className="history-item" key={date}><span className="history-icon"><Recycle /></span><div><strong>{type} recycling</strong><small>{date} · {weight}</small></div><em>{points}</em><span className="done"><Check /></span></div>)}</div></div> }
function Badges({ go }: { go: (screen: Screen) => void }) { const badges = [['First Recycle', Recycle, true], ['10 kg Recycled', PackageCheck, true], ['Eco Warrior', Leaf, false], ['Green Champion', Trophy, false]]; return <div className="screen"><Header title="My Badges" back go={go} /><p className="subtle badge-intro">Keep recycling to unlock new achievements.</p><div className="badge-grid">{badges.map(([label, Icon, unlocked]) => { const BadgeIcon = Icon as typeof Leaf; return <button className={unlocked ? 'badge unlocked' : 'badge'} key={label as string} onClick={() => window.alert(`${label} is ${unlocked ? 'unlocked and active.' : 'still locked. Keep recycling!'}`)}><span><BadgeIcon /></span><strong>{label as string}</strong><small>{unlocked ? 'Unlocked' : 'Locked'}</small></button> })}</div></div> }

function Splash({ onStart }: { onStart: () => void }) { return <main className="splash"><div className="splash-logo"><Leaf /></div><h1>SCWT</h1><p>Recycle Today, Save Tomorrow</p><div className="cityline" aria-hidden="true"><span /><span /><span /><span /><span /></div><div className="splash-copy">Together we can<br />build a greener future</div><button className="splash-button" onClick={onStart}>Get Started</button></main> }

function AuthShell({ children, title, subtitle, onBack }: { children: React.ReactNode; title: string; subtitle: string; onBack: () => void }) { return <main className="auth-page"><div className="auth-card"><button className="auth-back" onClick={onBack} aria-label="Back to welcome"><ArrowLeft /></button><div className="auth-brand"><LeafMark /><strong>SCWT</strong></div><div className="auth-heading"><h1>{title}</h1><p>{subtitle}</p></div>{children}</div></main> }

function Login({ onBack, onSignup, onSuccess }: { onBack: () => void; onSignup: () => void; onSuccess: () => void }) { const [studentId, setStudentId] = useState(''); const [phone, setPhone] = useState(''); const [error, setError] = useState(''); const submit = (event: React.FormEvent) => { event.preventDefault(); if (!studentId.trim() || phone.replace(/\\D/g, '').length < 8) { setError('Enter a valid Student ID and phone number.'); return } setError(''); onSuccess() }; return <AuthShell title="Welcome back" subtitle="Sign in to continue your recycling journey." onBack={onBack}><form className="auth-form" onSubmit={submit}><label>Student ID<input value={studentId} onChange={event => setStudentId(event.target.value)} placeholder="e.g. ECO-2024-001" autoComplete="username" /></label><label>Phone number<input value={phone} onChange={event => setPhone(event.target.value)} placeholder="e.g. +1 555 123 4567" type="tel" autoComplete="tel" /></label>{error && <p className="auth-error" role="alert">{error}</p>}<button className="primary-button" type="submit">Login</button></form><p className="auth-switch">New to SCWT? <button onClick={onSignup}>Create an account</button></p></AuthShell> }

function Signup({ onBack, onLogin, onSuccess }: { onBack: () => void; onLogin: () => void; onSuccess: () => void }) { const [studentId, setStudentId] = useState(''); const [phone, setPhone] = useState(''); const [error, setError] = useState(''); const submit = (event: React.FormEvent) => { event.preventDefault(); if (studentId.trim().length < 4 || phone.replace(/\\D/g, '').length < 8) { setError('Student ID must be at least 4 characters and phone must be valid.'); return } setError(''); onSuccess() }; return <AuthShell title="Create your account" subtitle="Join your campus community and make an impact." onBack={onBack}><form className="auth-form" onSubmit={submit}><label>Student ID<input value={studentId} onChange={event => setStudentId(event.target.value)} placeholder="e.g. ECO-2024-001" autoComplete="username" /></label><label>Phone number<input value={phone} onChange={event => setPhone(event.target.value)} placeholder="e.g. +1 555 123 4567" type="tel" autoComplete="tel" /></label>{error && <p className="auth-error" role="alert">{error}</p>}<button className="primary-button" type="submit">Sign up</button></form><p className="auth-switch">Already have an account? <button onClick={onLogin}>Login</button></p></AuthShell> }

export default function Page() { const [started, setStarted] = useState(false); const [auth, setAuth] = useState<AuthScreen>('login'); const [screen, setScreen] = useState<Screen>('home'); const [authenticated, setAuthenticated] = useState(false); if (!started) return <Splash onStart={() => setStarted(true)} />; if (!authenticated) return auth === 'login' ? <Login onBack={() => setStarted(false)} onSignup={() => setAuth('signup')} onSuccess={() => setAuthenticated(true)} /> : <Signup onBack={() => setStarted(false)} onLogin={() => setAuth('login')} onSuccess={() => setAuth('login')} />; const props = { go: setScreen }; return <main className="app-shell"><div className="app-frame">{screen === 'home' && <Home {...props} />}{screen === 'schedule' && <Schedule {...props} />}{screen === 'scan' && <Scan {...props} />}{screen === 'rewards' && <Rewards {...props} />}{screen === 'impact' && <Impact {...props} />}{screen === 'profile' && <Profile {...props} />}{screen === 'history' && <History {...props} />}{screen === 'badges' && <Badges {...props} />}{['home', 'history', 'rewards', 'profile'].includes(screen) && <BottomNav screen={screen} go={setScreen} />}</div></main> }
