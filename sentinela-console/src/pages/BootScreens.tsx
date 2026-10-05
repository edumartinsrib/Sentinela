import { Button, FullScreenLoader, StatusCard } from 'broto-ui';
import { TriangleAlert } from 'lucide-react';
import { isApiError } from '../api/client';
import { SentinelaBrand } from '../components/Brand';

export function BootMessage({ message }: { message: string }) {
  return <FullScreenLoader brand={<SentinelaBrand tone="dark" />} label={message} />;
}

export function BootError({ error, title = 'Não foi possível iniciar o console' }: { error: unknown; title?: string }) {
  const detail = isApiError(error) ? error.detail : error instanceof Error ? error.message : String(error);
  return (
    <StatusCard
      brand={<SentinelaBrand tone="dark" />}
      tone="danger"
      icon={<TriangleAlert size={22} />}
      title={title}
      description={detail}
      action={
        <Button variant="primary" onClick={() => window.location.reload()}>
          Tentar de novo
        </Button>
      }
    />
  );
}
