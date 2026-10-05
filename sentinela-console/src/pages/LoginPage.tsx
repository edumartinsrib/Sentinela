import { AuthCard, AuthLayout, Button, Callout, Field, Input } from 'broto-ui';
import { LogIn } from 'lucide-react';
import { useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router';
import { authMode, getDevUser, setDevUser, signIn } from '../api/auth';
import { SentinelaBrand } from '../components/Brand';
import { useConfig } from '../lib/context';

export function LoginPage() {
  const config = useConfig();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get('next') || '/';
  const [username, setUsername] = useState('');

  if (authMode() === 'dev' && getDevUser()) return <Navigate to={next} replace />;

  const brand = <SentinelaBrand size={44} />;
  return (
    <AuthLayout
      brand={brand}
      tagline={
        <>
          Padrões do time em cada pull request. <br />A IA revisa; havendo apontamento, outra pessoa decide. O merge só passa liberado.
        </>
      }
      version={`v${config.version}`}
      mobileBrand={<SentinelaBrand tone="dark" />}
    >
      {config.auth.mode === 'oidc' ? (
        <AuthCard title="Entrar" description="Use a conta corporativa.">
          <Button variant="primary" size="lg" block icon={<LogIn size={16} />} onClick={() => void signIn(next)}>
            Entrar com SSO
          </Button>
        </AuthCard>
      ) : (
        <AuthCard
          title="Entrar"
          description="Ambiente de desenvolvimento: informe só o usuário."
          onSubmit={() => {
            if (!username.trim()) return;
            setDevUser(username);
            navigate(next, { replace: true });
          }}
        >
          <Field label="Usuário" hint="Ex.: admin, ana (dev), bia (revisora), caio (tech lead)">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
          </Field>
          <Button type="submit" variant="primary" size="lg" block icon={<LogIn size={16} />} disabled={!username.trim()}>
            Entrar
          </Button>
          <Callout tone="info">Modo dev: sem senha. Em produção o login é por OIDC (Entra ID, Keycloak…).</Callout>
        </AuthCard>
      )}
    </AuthLayout>
  );
}
