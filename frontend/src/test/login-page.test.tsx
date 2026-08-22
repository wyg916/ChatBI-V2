import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { LoginPage } from '../pages/LoginPage';

afterEach(cleanup);

function renderLogin() {
  const router = createMemoryRouter(
    [
      { path: '/login', element: <LoginPage /> },
      { path: '/', element: <h1>今天想了解哪些业务数据？</h1> },
    ],
    { initialEntries: ['/login'] },
  );

  render(<RouterProvider router={router} />);
  return router;
}

describe('LoginPage', () => {
  it('renders the approved product message and accessible login controls', () => {
    renderLogin();

    expect(screen.getByRole('heading', { name: /让每一个业务问题/ })).toBeVisible();
    expect(screen.getByRole('heading', { name: '登录工作空间' })).toBeVisible();
    expect(screen.getByLabelText('账号或电子名')).toHaveAttribute('autocomplete', 'username');
    expect(screen.getByLabelText('密码')).toHaveAttribute('type', 'password');
    expect(screen.getByRole('checkbox', { name: '记住登录' })).toBeChecked();
    expect(screen.getByRole('button', { name: '登录 ChatBI Studio' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '忘记密码?' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '服务条款' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '隐私政策' })).toBeDisabled();
  });

  it('supports changing the remember-login preference', async () => {
    const user = userEvent.setup();
    renderLogin();
    const remember = screen.getByRole('checkbox', { name: '记住登录' });

    await user.click(remember);
    expect(remember).not.toBeChecked();
  });
});
