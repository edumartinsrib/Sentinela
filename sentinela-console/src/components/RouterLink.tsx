import { forwardRef } from 'react';
import { Link, type LinkProps } from 'react-router';

// Adaptador do react-router para a broto-ui (os componentes da lib recebem `href`).
export const RouterLink = forwardRef<HTMLAnchorElement, Omit<LinkProps, 'to'> & { href: string }>(
  ({ href, ...rest }, ref) => <Link ref={ref} to={href} {...rest} />,
);
RouterLink.displayName = 'RouterLink';
