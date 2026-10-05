import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Grid,
  Input,
  LinkButton,
  Page,
  PageHeader,
  Skeleton,
  Switch,
  Tag,
  Textarea,
  toast,
  useDocumentTitle,
} from 'broto-ui';
import { BookCheck, FileUp, Plus } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useLibrary, useProfileActions, useProfiles } from '../api/queries';
import type { Category, ProfileSummary } from '../api/types';
import { useTeam } from '../lib/context';
import { CATEGORY } from '../lib/labels';

export function ProfilesPage() {
  const { team, base, can } = useTeam();
  const profiles = useProfiles(team.name);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  useDocumentTitle('Padrões', 'Sentinela');
  const canWrite = can('standards.write');

  return (
    <Page>
      <PageHeader
        title="Padrões"
        description="Um perfil reúne as regras de um tipo de implementação (API Python, front React, Terraform…). Cada repositório aplica um ou mais perfis, e os arquivos de cada perfil são escolhidos pelos caminhos."
        actions={
          canWrite && (
            <>
              <Button variant="secondary" icon={<FileUp size={16} />} onClick={() => setImporting(true)}>
                Importar YAML
              </Button>
              <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
                Novo perfil
              </Button>
            </>
          )
        }
      />
      {profiles.isError ? (
        <Card>
          <ErrorState error={profiles.error} onRetry={() => void profiles.refetch()} />
        </Card>
      ) : profiles.isLoading ? (
        <Grid layout="cards">
          {[0, 1, 2].map((i) => (
            <Card key={i}>
              <Skeleton height={120} />
            </Card>
          ))}
        </Grid>
      ) : profiles.data?.length === 0 ? (
        <Card>
          <EmptyState
            icon={<BookCheck size={22} />}
            title="Nenhum perfil de padrão"
            description="Comece por um modelo pronto (API Python, React, Java, Terraform, pipelines) e ajuste as regras ao seu time."
            action={
              canWrite && (
                <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
                  Criar perfil
                </Button>
              )
            }
          />
        </Card>
      ) : (
        <Grid layout="cards">
          {profiles.data?.map((p) => <ProfileCard key={p.id} profile={p} base={base} />)}
        </Grid>
      )}
      {canWrite && <CreateProfileDialog open={creating} onClose={() => setCreating(false)} />}
      {canWrite && <ImportDialog open={importing} onClose={() => setImporting(false)} />}
    </Page>
  );
}

function ProfileCard({ profile, base }: { profile: ProfileSummary; base: string }) {
  const cats = Object.entries(profile.rules_by_category) as [Category, number][];
  return (
    <Card box>
      <div className="snt-profile-card">
        <div className="snt-between">
          <strong style={{ fontSize: '1.05rem' }}>{profile.name}</strong>
          {!profile.enabled && <Badge tone="neutral">desabilitado</Badge>}
        </div>
        {profile.description && <span className="snt-muted snt-small">{profile.description}</span>}
        <div className="snt-inline">
          {profile.path_globs.length ? (
            profile.path_globs.slice(0, 4).map((g) => (
              <Tag key={g} mono>
                {g}
              </Tag>
            ))
          ) : (
            <Tag mono>todos os arquivos</Tag>
          )}
          {profile.path_globs.length > 4 && <Tag>+{profile.path_globs.length - 4}</Tag>}
        </div>
        <div className="snt-inline snt-small">
          <strong>{profile.rules_enabled}</strong> regras ativas
          <span className="snt-muted">
            ({profile.rules_by_kind.ai ?? 0} IA · {profile.rules_by_kind.pattern ?? 0} padrão)
          </span>
          {profile.blocking_rules > 0 && (
            <Badge tone="danger" size="sm">
              {profile.blocking_rules} de severidade alta ou bloqueante
            </Badge>
          )}
        </div>
        <div className="snt-inline snt-small snt-muted snt-grow">
          {cats.map(([c, n]) => (
            <span key={c}>
              {CATEGORY[c]} {n}
            </span>
          ))}
        </div>
        <div className="snt-between">
          <span className="snt-small snt-muted">
            {profile.repositories.length
              ? `Usado em ${profile.repositories.map((r) => r.name).join(', ')}`
              : 'Ainda não usado em repositórios'}
          </span>
          <LinkButton size="sm" variant="secondary" href={`${base}/padroes/${profile.id}`}>
            Abrir
          </LinkButton>
        </div>
      </div>
    </Card>
  );
}

function CreateProfileDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { team, base } = useTeam();
  const navigate = useNavigate();
  const library = useLibrary();
  const { create } = useProfileActions(team.name);
  const [template, setTemplate] = useState<string | null>('python-api');
  const [name, setName] = useState('');

  const chosen = library.data?.templates.find((t) => t.key === template);
  const submit = async () => {
    const profile = await create.mutateAsync({ name: name.trim() || chosen?.name || 'Novo perfil', template });
    toast.success('Perfil criado', `${profile.rules_total} regras.`);
    onClose();
    navigate(`${base}/padroes/${profile.id}`);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Novo perfil de padrão"
      description="Escolha um modelo para começar com regras prontas, ou comece em branco."
      onSubmit={() => void submit()}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Criar perfil
          </Button>
        </>
      }
    >
      <div className="snt-stack">
        <div className="snt-templates" role="group" aria-label="Modelos">
          {library.data?.templates.map((t) => (
            <button
              type="button"
              key={t.key}
              className="snt-template"
              aria-pressed={template === t.key}
              onClick={() => setTemplate(t.key)}
            >
              <strong>{t.name}</strong>
              <span className="snt-small snt-muted">{t.description}</span>
              <span className="snt-small">{t.rules} regras</span>
            </button>
          ))}
          <button type="button" className="snt-template" aria-pressed={template === null} onClick={() => setTemplate(null)}>
            <strong>Em branco</strong>
            <span className="snt-small snt-muted">Sem regras; você monta do zero ou pela biblioteca.</span>
          </button>
        </div>
        <Field label="Nome" hint={chosen ? `Padrão: ${chosen.name}` : 'Ex.: API Python, Front-end React'} required={!chosen}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={chosen?.name} />
        </Field>
      </div>
    </Dialog>
  );
}

function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { team, base } = useTeam();
  const navigate = useNavigate();
  const { importYaml } = useProfileActions(team.name);
  const [yaml, setYaml] = useState('');
  const [replace, setReplace] = useState(false);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Importar perfil (YAML)"
      description="O mesmo formato do Exportar. Com “substituir”, um perfil de mesmo nome recebe as regras do arquivo."
      onSubmit={async () => {
        const profile = await importYaml.mutateAsync({ yaml, replace });
        toast.success('Perfil importado', profile.name);
        onClose();
        navigate(`${base}/padroes/${profile.id}`);
      }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" loading={importYaml.isPending} disabled={yaml.trim().length < 10}>
            Importar
          </Button>
        </>
      }
    >
      <div className="snt-stack">
        <Field label="Conteúdo do arquivo">
          <Textarea code rows={14} value={yaml} onChange={(e) => setYaml(e.target.value)} placeholder={'name: API Python\npath_globs: ["**/*.py"]\nrules:\n  - code: SEC-001\n    title: …'} />
        </Field>
        <Switch checked={replace} onCheckedChange={setReplace} label="Substituir se já existir um perfil com esse nome" />
      </div>
    </Dialog>
  );
}
