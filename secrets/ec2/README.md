# EC2 Deploy Secrets

This directory is reserved for single-EC2 deployment secret files.

Only this README and `.gitkeep` should be committed. Real `*.txt` files in this
directory are local deployment secrets and must stay out of Git.

Prepare the expected files with:

```bash
make deploy-ec2-secrets-prepare
```

Required files are generated if missing:

- `secret_key.txt`
- `postgres_password.txt`
- `redis_password.txt`

Optional integration files are created empty. Fill only the files needed by the
providers enabled in `deploy/.env.ec2`.

## Secrets Manager compatibility

The file names remain the runtime contract even when AWS Secrets Manager is the
upstream source. `deploy/runtime-secret-manifest.json` is the non-secret
allowlist and maps each JSON key to the matching `*.txt` file.

Inspect file presence without printing values:

```bash
make deploy-secrets-status
make deploy-secrets-aws-status
```

Preview an import:

```bash
make deploy-secrets-import \
  ARGS="--ssm-override postgres_password=/dewflow/prod/postgres_password"
```

The import is dry-run by default. Add `--apply` only after reviewing the key
names. Existing Secrets Manager values are never replaced unless
`--update-existing` is also explicit; updates merge keys and do not remove
existing values.

On EC2, set the following only after the AWS bundle and instance role have been
validated:

```dotenv
DEPLOY_SECRET_SOURCE=aws
DEPLOY_SECRET_DIR=/run/dewflow-secrets
DEPLOY_RUNTIME_SECRET_ID=dewflow-prod-runtime
```

`make deploy-secrets-materialize` then expands the AWS JSON bundle into the same
file names before the existing deploy checks run. Keep `secrets/ec2` as a
temporary migration fallback until the runtime and database login checks pass;
do not commit, copy, or casually export its values.
