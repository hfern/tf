# Caveats

This package works great for development and testing, but there are some caveats to be aware of before you can take it to production.

HashiCorp expects providers to be written in Go using Terraform Plugin Framework.
This compiles the provider down into a single binary (per os/arch) that can be distributed to users.
That's the accepted way to write a provider and their tooling and documentation is built around this.

This is very different from the Python ecosystem, where we expect users to have Python installed and to install packages from PyPI.
A lot of frustrations come from this difference in expectations.
_It's an uphill battle to get a Python provider into production._

If you want to write a provider in Python for production use, you will have to overcome these hurdles.
It's doable, but **outside of scope of this package and you're on your own.**

You should very strongly consider only using this package for development, testing, and proof-of-concept work.

#### What's the big problem?

The biggest problem is that Terraform **expects the provider to be a single binary**.
You need to get your entire artifact into one executable file that you can move to someone else's machine.
This is VERY at odds with the default Python experience.

To get around this, you can use something like [Pex](https://docs.pex-tool.org/) to generate a single binary.
While this works for simple (pure Python) packages, you need to consider:

* How many OS/Architecture combinations do you need to support?
* How old of a version of GLIBC are you are targeting? Prepare to bake pre-prepared `--complete-platform` configuration sets for every combination you want to support.
* Do any of your dependencies have C extensions? Or do dynamic linking?
  This might be a dealbreaker.

With a lot of project-specific configuration, you can get this working and building a single `terraform-provider-$providername`. But YMMV.

See [Building a Binary](tips_tricks.html#building-a-binary) for some tips and tricks to get this working.

#### Development mode already works, why not use that?

Without single-binaries you need to use developer mode and a hack.

In TF, developer mode is essentially an override telling TF to look for the provider binary in a specific location.

```hcl
provider_installation {
  dev_overrides {
      "tf.mydomain.com/mypackage" = "/path/to/your/.venv/bin"
  }
  
  direct {}
}
```

This package abuses this by symlinking the "binary" to app's script's entrypoint in the package, which is just a shell script that fires up Python and points to your entrypoint function.
When TF executes the "binary", it's actually running bash, which runs the Python interpreter, which runs your code.

There are two drawbacks with this approach for production:

##### No Lockfiles

First, the most serious drawback is that this prevents generating a lockfile.
In practice, this means you cannot use other providers at the same time as your Python provider.
You will eventually want to mix-and-match providers, and you will need to have a lockfile to do that.
No lockfile means no mixing providers.

##### Versioning Mismatch

Without lockfiles, you are going to end up with a versioning mismatch.

Normally, each TF project consumes providers and each project has its own lockfile.
TF can vary which provider version it uses based on the lockfile for each project.

Without a lockfile and while using developer mode, all TF projects on your machine will use the same installed
version of the provider. This can lead to versioning mismatches and bugs that are hard to track down.

You'll need to checkout the correct version of your provider for each project in one directory or repo before consuming it in a different folder.
This is a huge pain and an accident waiting to happen.


#### Preparing for Registry Upload

Once you have single binaries ready for each OS/Arch, you need to generate hash sums, sign them, and generate a manifest.
In theory, the official HashiCorp registry will allow you to upload these binaries and metadata using the standard Github release workflow.

However, I would strongly consider using a private registry or a different distribution method.
HashiCorp will almost certainly not officially approve and verify your provider for [the integration program](https://developer.hashicorp.com/terraform/docs/partnerships).

You will have to set that up yourself.
