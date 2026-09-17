import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ErrorNotice, PageHeading, StatusBadge } from '../components/UI';

describe('core UI components', () => {
  it('renders page hierarchy and actions', () => {
    render(<PageHeading title="数据源" description="连接业务数据库" actions={<button>新建</button>}/>);
    expect(screen.getByRole('heading', { name: '数据源' })).toBeVisible();
    expect(screen.getByText('连接业务数据库')).toBeVisible();
    expect(screen.getByRole('button', { name: '新建' })).toBeEnabled();
  });
  it('maps backend status to neutral business labels', () => {
    const { rerender } = render(<StatusBadge status="CONNECTED"/>); expect(screen.getByText('正常')).toBeVisible();
    rerender(<StatusBadge status="DRAFT"/>); expect(screen.getByText('草稿')).toBeVisible();
  });
  it('shows actionable API errors', () => {
    render(<ErrorNotice error={new Error('连接超时')}/>); expect(screen.getByText('连接超时')).toBeVisible();
  });
});
