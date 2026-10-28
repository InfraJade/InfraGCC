import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

import { Icon, type IconName } from './Icon';
import { Spinner } from './Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: IconName;
  iconRight?: IconName;
  loading?: boolean;
  children?: ReactNode;
}

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-on-accent hover:bg-accent-hover shadow-sm',
  secondary: 'glass-subtle text-text hover:bg-text/10',
  ghost: 'text-text-muted hover:text-text hover:bg-text/5',
  danger: 'bg-health-critical text-canvas hover:bg-health-critical/90 shadow-sm',
};

const sizes: Record<ButtonSize, string> = {
  sm: 'h-8 px-2.5 text-xs gap-1.5',
  md: 'h-9 px-3.5 text-sm gap-2',
  lg: 'h-11 px-5 text-sm gap-2',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    icon,
    iconRight,
    loading,
    disabled,
    className,
    children,
    type = 'button',
    ...rest
  },
  ref,
) {
  const iconSize = size === 'sm' ? 14 : 16;
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex select-none items-center justify-center whitespace-nowrap rounded-md font-medium transition duration-fast ease-standard disabled:cursor-not-allowed disabled:opacity-50',
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner size={iconSize} /> : icon ? <Icon name={icon} size={iconSize} /> : null}
      {children}
      {iconRight ? <Icon name={iconRight} size={iconSize} /> : null}
    </button>
  );
});

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  icon: IconName;
  /** Required accessible name (also the tooltip). */
  label: string;
  size?: ButtonSize;
  variant?: ButtonVariant;
  badge?: ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, size = 'md', variant = 'ghost', badge, className, type = 'button', ...rest },
  ref,
) {
  const box = size === 'sm' ? 'h-8 w-8' : size === 'lg' ? 'h-11 w-11' : 'h-9 w-9';
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        'relative inline-flex items-center justify-center rounded-md transition duration-fast ease-standard disabled:opacity-50',
        variants[variant],
        box,
        className,
      )}
      {...rest}
    >
      <Icon name={icon} size={size === 'sm' ? 15 : 18} />
      {badge}
    </button>
  );
});
