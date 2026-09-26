# GitHub Actions -> AWS trust, via OIDC. No static access keys anywhere:
# GitHub mints a short-lived token per workflow run, which this role trusts
# only when it claims to come from this exact repo on an allowed branch.

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]

  tags = var.tags
}

data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      # GitHub's sub claim now appends immutable numeric IDs after `@` for
      # both org and repo (repo:OWNER@OWNER_ID/REPO@REPO_ID:ref:...), not
      # the classic repo:OWNER/REPO:ref:... format most docs still show —
      # confirmed by decoding an actual token from this workflow. The `@*`
      # wildcards only the ID portion; org/repo names are still exact-matched.
      values = [
        for branch in var.allowed_branches :
        "repo:${var.github_org}@*/${var.github_repo}@*:ref:refs/heads/${branch}"
      ]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "managed" {
  for_each   = toset(var.managed_policy_arns)
  role       = aws_iam_role.github_actions.name
  policy_arn = each.value
}
