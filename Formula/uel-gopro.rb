class UelGopro < Formula
  include Language::Python::Virtualenv

  desc "Unofficial Extended Life GoPro CLI toolchain"
  homepage "https://github.com/StrangeSid/uel-gopro"
  license "GPL-3.0-or-later"
  head "https://github.com/StrangeSid/uel-gopro.git", branch: "main"

  # There is no stable Homebrew release yet. Install with:
  #   brew install --HEAD ./Formula/uel-gopro.rb
  depends_on "python@3.13"
  depends_on "ffmpeg"

  def install
    venv = virtualenv_create(libexec, "python3.13")
    venv.pip_install buildpath
    bin.install_symlink libexec/"bin/uel-gopro"
  end

  test do
    assert_match "uel-gopro", shell_output("#{bin}/uel-gopro --help")
  end
end
