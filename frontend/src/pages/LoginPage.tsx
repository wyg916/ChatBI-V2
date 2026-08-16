import { useNavigate } from 'react-router-dom';

export function LoginPage() {
  const navigate = useNavigate();
  return <div className="login-page"><div className="login-visual"><div className="brand login-brand"><span className="brand-mark">BI</span><div><strong>ChatBI Studio</strong><small>让每一个业务问题，都有可信的数据答案</small></div></div><div className="orb one"/><div className="orb two"/></div><form className="login-card" onSubmit={(e) => { e.preventDefault(); navigate('/'); }}><span className="eyebrow">欢迎回来</span><h1>登录工作空间</h1><p>使用企业账号继续访问 ChatBI</p><label>邮箱<input type="email" defaultValue="admin@chatbi.local" required /></label><label>密码<input type="password" defaultValue="chatbi-demo" required /></label><button className="button primary">登录</button><small>演示环境 · 请勿录入真实敏感数据</small></form></div>;
}
