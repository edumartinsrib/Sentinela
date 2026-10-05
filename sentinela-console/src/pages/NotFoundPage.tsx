import { LinkButton, NotFound, Page } from 'broto-ui';

export function NotFoundPage({ inShell = false }: { inShell?: boolean }) {
  const content = (
    <NotFound
      title="Página não encontrada"
      description="O endereço não existe ou foi movido."
      action={
        <LinkButton href="/" variant="primary">
          Ir para o início
        </LinkButton>
      }
    />
  );
  return inShell ? <Page>{content}</Page> : content;
}
