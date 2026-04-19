FROM node:20-slim

WORKDIR /app

COPY hardhat/package*.json ./
RUN npm ci

COPY hardhat/ .

EXPOSE 8545
CMD ["npx", "hardhat", "node", "--hostname", "0.0.0.0"]
