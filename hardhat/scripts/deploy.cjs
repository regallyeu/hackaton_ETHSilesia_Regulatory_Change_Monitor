const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const Factory = await hre.ethers.getContractFactory("AlertAnchor");
  const c = await Factory.deploy();
  await c.waitForDeployment();
  const addr = await c.getAddress();
  console.log("Deployer:", deployer.address);
  console.log("AlertAnchor:", addr);
  console.log("");
  console.log("PowerShell (after running: npm run node):");
  console.log(
    `$env:ANCHOR_BACKEND=\"evm\"; $env:EVM_RPC_URL=\"http://127.0.0.1:8545\"; $env:EVM_CHAIN_ID=\"31337\"; $env:EVM_CONTRACT_ADDRESS=\"${addr}\"; $env:EVM_PRIVATE_KEY=\"0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80\"`
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
