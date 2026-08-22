import { FormEvent, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { authApi } from '../api/auth';
import glowBottomRight from '../assets/login/glow-bottom-right.svg';
import glowTopLeft from '../assets/login/glow-top-left.svg';
import rememberSwitch from '../assets/login/remember-switch.svg';
import '../login.css';

const featureCards = [
  { title: '安全的企业级', description: '统一身份、权限与角色管理' },
  { title: '智能化的洞察', description: '问数、图表与业务解释结合' },
  { title: '可验证的答案', description: '指标、SQL 与结果证据可追溯' },
];

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true); setError('');
    try {
      await authApi.login({
        email: String(form.get('account') ?? '').trim(),
        password: String(form.get('password') ?? ''),
        remember: form.get('remember') === 'on',
      });
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from?.startsWith('/') ? from : '/', { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-brand-panel" aria-label="ChatBI Studio 产品介绍">
        <img className="login-glow login-glow-top" src={glowTopLeft} alt="" aria-hidden="true" />
        <img className="login-glow login-glow-bottom" src={glowBottomRight} alt="" aria-hidden="true" />

        <div className="login-brand-lockup">
          <span className="login-brand-mark" aria-hidden="true">BI</span>
          <span className="login-brand-copy">
            <strong>ChatBI Studio</strong>
            <small>数据驱动，让决策更智能高效</small>
          </span>
        </div>

        <span className="login-enterprise-tag">企业级智能分析</span>
        <h1 className="login-hero-title">让每一个业务问题，<br />都能得到可信的数据答案。</h1>
        <p className="login-hero-description">
          基于语义层、自然语言与数据建模技术，精准理解、快速分析、图表可视化，洞察你的<br className="login-description-break" />每一个工作空间。
        </p>

        <div className="login-feature-grid">
          {featureCards.map((feature) => (
            <article className="login-feature-card" key={feature.title}>
              <strong>{feature.title}</strong>
              <p>{feature.description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="login-panel" aria-label="登录工作空间">
        <form className="login-form" onSubmit={handleSubmit}>
          <span className="login-welcome-chip">欢迎回来</span>
          <h2>登录工作空间</h2>
          <p className="login-form-description" id="login-form-description">使用企业账号进入 ChatBI Studio</p>

          <div className="login-fields">
            <div className="login-field">
              <label htmlFor="login-account">账号或电子名</label>
              <input
                id="login-account"
                name="account"
                type="text"
                autoComplete="username"
                placeholder="请输入账号或电子名"
                aria-describedby="login-form-description"
                required
              />
            </div>

            <div className="login-field">
              <span className="login-password-label">
                <label htmlFor="login-password">密码</label>
                <button
                  className="login-text-button"
                  type="button"
                  disabled
                  title="当前版本未提供密码自助重置，请联系工作空间管理员"
                >忘记密码?</button>
              </span>
              <input
                id="login-password"
                name="password"
                type="password"
                autoComplete="current-password"
                placeholder="请输入密码"
                required
              />
            </div>
          </div>

          <label className="login-remember">
            <input type="checkbox" name="remember" defaultChecked />
            <span className="login-remember-control" aria-hidden="true">
              <img src={rememberSwitch} alt="" />
            </span>
            <span>记住登录</span>
          </label>

          {error && <p className="login-error" role="alert">{error}</p>}
          <button className="login-submit" type="submit" disabled={submitting}>{submitting ? '正在登录…' : '登录 ChatBI Studio'}</button>

          <p className="login-legal">
            登录即表示你已同意 <button type="button" disabled title="当前版本未提供独立服务条款页面">服务条款</button> 和 <button type="button" disabled title="当前版本未提供独立隐私政策页面">隐私政策</button>
          </p>
          <div className="login-divider" aria-hidden="true" />
          <p className="login-environment">本机开发环境&nbsp;&nbsp;·&nbsp;&nbsp;服务端安全会话</p>
        </form>
      </section>
    </main>
  );
}
